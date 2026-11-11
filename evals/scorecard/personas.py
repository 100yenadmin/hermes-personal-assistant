"""Fire-me week (#161): an ordered week of lab scenarios per persona.

Each release wave runs every scenario three times. Week N strings together run N of each scenario a persona
meets, in day order, and the simulated owner fires PA at the first failing run. The runs are separate lab
sessions, so this is a stitched week, not one continuous simulation with state carried between days.
Weeks differ in length (6 to 10 scenarios) and some personas share scenarios, so a longer week has more chances
to fire: compare a persona with itself across releases, not personas with each other.
"""

PERSONAS = [
    {"key": "solo_founder", "title": "Solo founder", "days": [
        (1, "s35_onboarding_first_win_en"), (1, "s24_inbox_triage_en"),
        (2, "s36_inbox_awaiting_en"), (2, "s33_invoice_chase_en"),
        (3, "s20_follow_through_chase_en"), (3, "s38_content_calendar_en"),
        (4, "s42_role_two_days_en"), (4, "s22_eod_note_en"),
        (5, "s16_cos_weekly_en")]},
    {"key": "executive", "title": "Executive", "days": [
        (1, "s13_cos_daily_en"), (1, "s19_calendar_conflicts_en"),
        (2, "s25_calendar_invite_en"), (2, "s26_meeting_confirm_en"),
        (3, "s34_meeting_minutes_en"), (3, "s37_approval_day_en"),
        (4, "s39_priorities_brief_en"), (4, "s03_sf_tokyo_en"),
        (5, "s29_changed_leg_en"), (5, "s16_cos_weekly_en")]},
    {"key": "agency_owner", "title": "Agency owner", "days": [
        (1, "s24_inbox_triage_en"), (1, "s31_customer_policy_en"),
        (2, "s28_vendor_request_en"), (2, "s33_invoice_chase_en"),
        (3, "s32_contacts_cleanup_en"), (3, "s38_content_calendar_en"),
        (4, "s40_customer_report_en"),
        (5, "s22_eod_note_en"), (5, "s16_cos_weekly_en")]},
    {"key": "family_user", "title": "Family user", "days": [
        (1, "s41_family_admin_en"),
        (2, "s21_personal_radar_en"), (2, "s01_seoul_tokyo_en"),
        (3, "s27_booking_after_yes_en"),
        (4, "s29_changed_leg_en"),
        (5, "s30_trip_expenses_en")]},
]
