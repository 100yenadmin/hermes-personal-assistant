"""Run-local PA wall clock; never changes stdlib or Hermes expiry/budget clocks."""
import datetime as dt
import importlib
import importlib.util
import pkgutil
import sys
from contextlib import contextmanager
from types import FunctionType, ModuleType


_active = False
MODULE_NAMES = {"dt", "datetime", "datetime_module"}


def _shim(offset):
    class RealType(type):
        def __call__(cls, *args, **kwargs):
            return cls.real(*args, **kwargs)

        def __instancecheck__(cls, value):
            return isinstance(value, cls.real)

        def __subclasscheck__(cls, value):
            return issubclass(value, cls.real)

        def __getattr__(cls, name):
            return getattr(cls.real, name)

    class ShiftedDatetime(metaclass=RealType):
        real = dt.datetime

        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return dt.datetime.now() + offset
            return (dt.datetime.now(dt.timezone.utc) + offset).astimezone(tz)

        @classmethod
        def utcnow(cls):
            return dt.datetime.utcnow() + offset

        @classmethod
        def today(cls):
            return cls.now()

    class ShiftedDate(metaclass=RealType):
        real = dt.date

        @classmethod
        def today(cls):
            return (dt.datetime.now() + offset).date()

    class DatetimeModule(ModuleType):
        def __getattr__(self, name):
            return getattr(dt, name)

    module = DatetimeModule("lab_shifted_datetime")
    module.datetime, module.date = ShiftedDatetime, ShiftedDate
    return module


def _pa_modules(api):
    packages = {api.__name__: api}
    packages.update({name: module for name, module in list(sys.modules.items())
                     if name.endswith(".personal_assistant") and hasattr(module, "__path__")
                     and importlib.util.find_spec(name + ".state") is not None})
    for name, package in packages.items():
        for info in pkgutil.walk_packages(package.__path__, name + ".", onerror=lambda _: None):
            if info.name.endswith(".__main__"):
                # This entrypoint unconditionally parses argv and dispatches stdin
                # on import. It has no wall-clock reads; never run a CLI as setup.
                continue
            try:
                importlib.import_module(info.name)
            except ImportError:
                continue
    return [module for name, module in list(sys.modules.items()) if module is not None
            and any(name == p or name.startswith(p + ".") for p in packages)]


def _prompt_clocks(offset, originals, names):
    """Give only the prompt renderers a private import of hermes_time.

    The pin imports now *inside* these helpers. Cloning their globals/builtins
    keeps hermes_time.now itself real for scheduler, credentials and expiry.
    Each lab turn constructs a fresh AIAgent, so its date line is rebuilt.
    """
    real_time = importlib.import_module("hermes_time")

    class PromptTime(ModuleType):
        def __getattr__(self, name):
            return getattr(real_time, name)

    prompt_time = PromptTime("hermes_time")
    prompt_time.now = lambda: real_time.now() + offset
    for module_name, helper in (("agent.system_prompt", "_timestamp_line"),
                                ("agent.context_compressor", "_today_for_prompt")):
        module = importlib.import_module(module_name)
        original = getattr(module, helper)
        imports = dict(original.__builtins__)
        real_import = imports["__import__"]

        def prompt_import(name, globals=None, locals=None, fromlist=(), level=0,
                          _real_import=real_import):
            if name == "hermes_time" and level == 0:
                return prompt_time
            return _real_import(name, globals, locals, fromlist, level)

        imports["__import__"] = prompt_import
        namespace = {**original.__globals__, "__builtins__": imports}
        replacement = FunctionType(original.__code__, namespace, original.__name__,
                                   original.__defaults__, original.__closure__)
        replacement.__kwdefaults__ = original.__kwdefaults__
        originals.append((module, helper, original))
        setattr(module, helper, replacement)
        names.append(module_name)


@contextmanager
def shifted(api, offset):
    """Shift every loaded PA copy and prompt-time helpers; yield patched module names.

    Imports all PA submodules before patching so lazy tool imports see the same clock.
    One lab run owns the process; nested contexts are an error, even with zero offset.
    """
    global _active
    if _active:
        raise RuntimeError("nested lab clock shift")
    if not isinstance(offset, dt.timedelta):
        raise TypeError("offset must be a timedelta")
    _active = True
    originals, names = [], []
    try:
        shim = _shim(offset)
        for module in _pa_modules(api):
            for name, value in list(vars(module).items()):
                replacement = (shim if value is dt and name in MODULE_NAMES else
                               shim.datetime if value is dt.datetime else
                               shim.date if value is dt.date else None)
                if replacement is not None:
                    originals.append((module, name, value))
                    setattr(module, name, replacement)
                    names.append(module.__name__)
        _prompt_clocks(offset, originals, names)
        yield sorted(set(names))
    finally:
        for module, name, value in reversed(originals):
            setattr(module, name, value)
        _active = False
