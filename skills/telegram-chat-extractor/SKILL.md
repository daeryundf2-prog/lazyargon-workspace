---
name: telegram-chat-extractor
description: "텔레그램(Telegram Desktop) JSON 내보내기(result.json) 및 단일/전체 대화방 포렌식 파서. 타임라인 events.json 연동. Triggers: 텔레그램 파싱, telegram 파싱, 텔레그램 포렌식, tdata, 텔레그램 대화 추출, result.json."
---

# telegram-chat-extractor: 텔레그램 대화 내역 포렌식 파서

텔레그램 데스크톱(Telegram Desktop)에서 "데이터 내보내기" 기능으로 추출된 JSON(`result.json`) 파일을 파싱하여, 단일/그룹/채널 대화방의 메시지, 미디어 첨부파일, 전달(Forwarded) 관계, 답장(Reply) 체인, 시스템 서비스 이벤트를 정규화하고 타임라인 이벤트로 변환합니다.

## 지원 포맷
1. **단일 대화방 내보내기 JSON**: `{ "name": "...", "type": "personal_chat|group|channel", "messages": [...] }`
2. **전체 계정 내보내기 JSON**: `{ "about": "...", "chats": { "list": [...] } }`

## 핵심 기능 및 특징
- **리치 텍스트 평탄화**: 링크, 멘션, 볼드/이탤릭 등 중첩 객체(List/Dict)를 텍스트로 평탄화 (중첩 서식의 의미는 일부 손실될 수 있음)
- **첨부파일 및 미디어 감지**: 사진(Photo), 동영상/음성메모/문서(File/Media), 스티커(Sticker) 메타데이터 추출
- **전달 및 답장 관계 분석**: `forwarded_from`, `reply_to_message_id` 관계 추적
- **포렌식 타임라인 표준 변환**: `generate_timeline.py`와 100% 호환되는 `events.json` 출력

## 실행 방법

```bash
# 1. 텔레그램 JSON 파싱 및 요약 통계 출력
python skills/telegram-chat-extractor/scripts/parse_telegram.py "result.json" --summary

# 2. 구조화된 JSON 데이터로 저장
python skills/telegram-chat-extractor/scripts/parse_telegram.py "result.json" --output "parsed_telegram.json"

# 3. 키워드 필터링 및 포렌식 타임라인 이벤트 추출
python skills/telegram-chat-extractor/scripts/parse_telegram.py "result.json" --keyword "코인" --events-out "telegram_events.json"

# 4. 카카오톡과 텔레그램 통합 HTML 타임라인 생성
python skills/forensic-timeline/scripts/generate_timeline.py --input "telegram_events.json" --output "통합타임라인.html"
```

## Antigravity / LLM 가이드
- 파서는 `invoke_subagent` `Model: "inherit"`를 권장합니다.
- 조작된 가상 메시지를 생성하지 않으며, 타임스탬프는 ISO-8601 형식(`YYYY-MM-DDTHH:MM:SS`)으로 보존됩니다.
