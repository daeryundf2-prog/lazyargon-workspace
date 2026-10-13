---
name: kakao-chat-extractor
description: 카카오톡 모바일/PC 텍스트 내보내기(.txt) 파싱. SQLite·백업 DB·대화방 폴더 탐색에는 쓰지 말 것.
---

# kakao-chat-extractor: 카카오톡 텍스트 내보내기 파서

지원 포맷은 아래 두 가지뿐이다.

1. **모바일 텍스트 내보내기**
   - `--------------- 2024년 1월 16일 화요일 ---------------`
   - `[홍길동] [오후 2:15] 안녕하세요.`
   - 초 단위가 없어 시각은 `:00`으로 기록한다.
2. **PC 텍스트 내보내기 (대화내용 저장)**
   - `=============== 2024년 1월 16일 화요일 ===============` (헤더)
   - `[오후 2:15] 홍길동 : 안녕하세요` (초 없음 → `:00`)
   - `[오후 3:05:30] 홍길동 : 사진` (초 있는 변형)
   - `[오후 12:05] 홍길동님이 나갔습니다.` 같은 시스템 이벤트는 `type: "system"` 레코드로 분리된다.
3. **레거시 합성 포맷 (하위 호환)**
   - `[2024-01-16 14:15:22] 홍길동: 안녕하세요.`

UTF-8, UTF-8 BOM, CP949(레거시 한국어 Windows), UTF-16 LE/BE를 시도한다.
모바일 메시지 앞에 날짜 헤더가 없으면 `timestamp`는 `null`, `timestamp_unknown`은 `true`다. 1970년 날짜를 만들지 않는다.
발신자/내용 구분은 첫 번째 ` : `(공백-콜론-공백)이며, 메시지 내부 콜론은 발신자에 섞이지 않는다.
첨부 판정은 내보내기의 확정 표기(사진 / 동영상 / `파일: ...` / `파일 전송`)뿐이다 — "사진 좀 보내줘" 같은 언급은 첨부가 아니다.
인식 불가 행은 버려지지 않고 `type: "unparsed"` 레코드로 보존된다.

## 하지 않는 일

- Android/iOS 백업, `chat_logs` SQLite, 암호화 DB
- 대화방 폴더 자동 탐색
- 실명·사건 당사자 예시 사용

## 실행

```bash
python skills/kakao-chat-extractor/scripts/parse_kakao.py "카카오톡_대화내용.txt" --keyword "키워드" --output parsed.json

# 타임라인용 events.json 을 같이 뽑을 수 있다 (시각 확정 레코드만 — 근거 없는 시각은 제외)
python skills/kakao-chat-extractor/scripts/parse_kakao.py "카카오톡_대화내용.txt" --output parsed.json --events-out events.json
```

## Antigravity

파서는 `invoke_subagent` `Model: "inherit"`. 검증은 `Model: "inherit"`(세션 모델과 무관, Claude 할당량 절약). 모바일 시각은 초가 없어 `:00`이다. `view_file`을 만들지 말 것.
