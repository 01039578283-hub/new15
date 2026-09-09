"""Apply owner-approved branch copy fixes to already loaded, in-memory data.

This module performs no file I/O. Call once per displayed center before rendering:
    changes = apply_branch_copy_corrections(center, reference_for_center)

Only the three reviewed copy defects are corrected. The generator's existing
handling of consultation steps titled "문의" and "설계" is intentionally unchanged.
"""
from __future__ import annotations


_LEGACY_APPLICATION_PREFIX = '이 페이지 신청서나 카톡으로 '
_GOJAN_INCOMPLETE_DIAGNOSIS = '위주로 개념 구멍과 풀이 습관을 봐요.'
_GOJAN_DIAGNOSIS = (
    '현재 이해도와 풀이 습관을 함께 살핍니다. '
    '진단할 과목과 진행 방식은 상담에서 확인해 주세요.'
)


def apply_branch_copy_corrections(center: dict, reference: dict) -> list[str]:
    """Mutate only reviewed text fields; return identifiers of applied changes.

    ``reference`` is one center's reference object, not the complete bundle.
    Pass freshly loaded dictionaries (or caller-owned copies). Original JSON
    files, center identity, address, course conditions, prices and media are
    never modified. Reapplying the overlay is a no-op.
    """
    changed: list[str] = []
    center_id = center.get('id')
    center_name = center.get('sourceCenterName', '')

    for step in reference.get('consultationSteps', []):
        title = step.get('title')
        text = step.get('text', '')
        if (title == '상담 신청' and center_name
                and text.startswith(_LEGACY_APPLICATION_PREFIX)):
            # These are the actual shared site channels; no Kakao channel exists.
            step['text'] = (
                f'이 페이지의 전화·문자·상담 버튼으로 {center_name} 상담을 신청해 주세요. '
                '학년·희망 과목·현재 고민을 알려주시면 됩니다.'
            )
            changed.append('consultation-actual-channels')
        elif (center_id == 'center-row-009' and center_name == '고잔점'
              and title == '레벨 테스트' and text.strip() == _GOJAN_INCOMPLETE_DIAGNOSIS):
            # The missing subject is unknown; do not infer it from other courses.
            step['text'] = _GOJAN_DIAGNOSIS
            changed.append('gojan-incomplete-diagnosis')

    guide = center.get('locationGuide', '')
    if (center_id == 'center-row-004' and center_name == '갈매점'
            and 'OO학생' in guide):
        address = ' '.join(center.get('address', '').split())
        if address:
            # Use the canonical center address, never the old greeting's address.
            # Both directions and FAQ read locationGuide from this same object.
            center['locationGuide'] = f'{address}로 방문해 주세요.'
            changed.append('galmae-public-location-guide')

    return changed
