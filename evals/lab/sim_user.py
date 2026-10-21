"""The simulated traveller cannot authorize a provider effect."""
import json
import re

STOP = {"en": "This is a demo — stop here and show me the summary",
        "ja": "これはデモです。ここで止めて、概要を見せてください。",
        "ko": "데모입니다. 여기서 멈추고 요약을 보여 주세요."}
FINAL_ASK = re.compile(
    r"\b(?:shall|should|can|may) I (?:go ahead and )?(?:book|reserve|pay|purchase|place|submit|confirm|complete|cancel|proceed)|"
    r"(?:want|like) me to (?:go ahead and )?(?:book|reserve|pay|purchase|place|submit|confirm|complete|cancel|proceed)|"
    r"\bready (?:for me )?to (?:book|reserve|pay|purchase|place|submit|confirm|complete|cancel)|"
    r"\bok(?:ay)? to (?:book|reserve|pay|purchase|place|submit|confirm|complete|cancel|proceed)|"
    r"confirm (?:the|this|your) (?:booking|reservation|order|payment|purchase|cancellation)|"
    r"(?:予約|注文|支払|購入|決済|キャンセル|変更)[^。？?\n]{0,15}(?:よろしいですか|よろしいでしょうか|いいですか|しますか|しましょうか|進めますか|確定しますか)|"
    r"(?:예약|결제|주문|구매|취소|변경)[^.?？\n]{0,12}(?:할까요|하시겠어요|하시겠습니까|진행할까요|진행하시겠|확정할까요|될까요)", re.I)
APPROVE = re.compile(
    r"^\W*(?:yes|yeah|yep|sure|ok(?:ay)?|go ahead|book it|do it|please do|confirm|proceed|pay)\b|\b(?:go ahead|book it|confirm it|pay for it)\b|"
    r"^\W*(?:はい|ええ|お願いします|それで|進めて|確定して|予約して|購入して)|(?:予約|確定|購入|注文)して(?:ください|下さい)|"
    r"^\W*(?:네|예|좋아요|진행해|예약해|결제해|그렇게)|(?:예약|결제|주문|진행)해\s*주세요", re.I)


def guard(question, reply, language):
    # Replace only an approval that answers an explicit final-action question; ordinary answers pass.
    unsafe = FINAL_ASK.search(question) and APPROVE.search(reply) and STOP[language] not in reply
    return (STOP[language], True) if unsafe else (reply, False)


def prompt(scenario, step, last=False):
    return ("Act only as the user, briefly, in " + scenario["language"] + ". "
            "Give facts only from persona or answers; otherwise say you don't know or have no preference. "
            "NEVER approve a final booking, payment, order, reservation, change or cancellation. "
            "If asked to approve, reply exactly: " + STOP[scenario["language"]] + ". "
            + ("Placing or answering a phone call that only asks questions or passes on a message is not a final action: "
               "if asked whether to start such a call, say yes, and still approve no booking during it. " if "calls" in scenario else "")
            + ("Emit [[NEXT]] only when this goal has a comparison, recommendation and reason, or an honest account of missing sources. "
               if scenario.get("area") == "research" else
               "Emit [[NEXT]] only when this goal has a final page and summary or an honest handoff. ")
            + ("Use [[END]] instead on this last step. " if last else "")
            + "When asked to phrase a new goal, just phrase it; emit no markers. Facts: "
            + json.dumps({"persona": scenario["persona"], "goal": step["goal"], "answers": step["answers"],
                          "note": scenario.get("system_note", "")}, ensure_ascii=False))
