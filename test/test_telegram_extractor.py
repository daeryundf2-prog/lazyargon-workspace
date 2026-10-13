# -*- coding: utf-8 -*-
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARSER = ROOT / "skills" / "telegram-chat-extractor" / "scripts" / "parse_telegram.py"
TIMELINE_GEN = ROOT / "skills" / "forensic-timeline" / "scripts" / "generate_timeline.py"


class TelegramExtractorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_single_chat_json_parsing(self):
        chat_data = {
            "name": "홍길동과의 대화",
            "type": "personal_chat",
            "id": 12345678,
            "messages": [
                {
                    "id": 101,
                    "type": "message",
                    "date": "2024-01-16T14:15:22",
                    "from": "홍길동",
                    "from_id": "user12345678",
                    "text": "안녕하세요, 포렌식 검토 요청건입니다."
                },
                {
                    "id": 102,
                    "type": "message",
                    "date": "2024-01-16T14:16:05",
                    "from": "이순신",
                    "from_id": "user87654321",
                    "reply_to_message_id": 101,
                    "text": [
                        "네 확인했습니다. 관련 링크는 ",
                        {"type": "link", "text": "https://example.com/evidence"},
                        " 참고 바랍니다."
                    ],
                    "photo": "photos/photo_1@16-01-2024_14-16-05.jpg",
                    "width": 1280,
                    "height": 720
                },
                {
                    "id": 103,
                    "type": "service",
                    "date": "2024-01-16T15:00:00",
                    "actor": "홍길동",
                    "action": "pin_message",
                    "message_id": 102
                }
            ]
        }
        json_path = self.tmp / "result.json"
        json_path.write_text(json.dumps(chat_data, ensure_ascii=False), encoding="utf-8")

        out_json = self.tmp / "parsed.json"
        events_out = self.tmp / "events.json"

        cmd = [
            sys.executable, str(PARSER), str(json_path),
            "--output", str(out_json),
            "--events-out", str(events_out),
            "--summary"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(res.returncode, 0, f"Parser failed: {res.stderr}")

        # Check parsed JSON
        with open(out_json, "r", encoding="utf-8") as f:
            parsed = json.load(f)
        self.assertEqual(len(parsed), 1)
        chat = parsed[0]
        self.assertEqual(chat["chat_name"], "홍길동과의 대화")
        self.assertEqual(chat["total_messages"], 3)
        self.assertEqual(chat["service_event_count"], 1)
        self.assertEqual(chat["participants"]["홍길동"], 1)
        self.assertEqual(chat["participants"]["이순신"], 1)

        # Check message 102 rich text flattening & photo attachment
        msg2 = chat["messages"][1]
        self.assertIn("https://example.com/evidence", msg2["text"])
        self.assertTrue(msg2["has_attachment"])
        self.assertEqual(msg2["attachments"][0]["type"], "photo")

        # Check events JSON
        with open(events_out, "r", encoding="utf-8") as f:
            events = json.load(f)
        self.assertEqual(len(events), 3)
        self.assertEqual(events[0]["category"], "chat")
        self.assertEqual(events[0]["source"], "Telegram")
        self.assertEqual(events[0]["actor"], "홍길동")

        # Verify timeline generation with generate_timeline.py
        timeline_html = self.tmp / "timeline.html"
        t_cmd = [
            sys.executable, str(TIMELINE_GEN),
            "--input", str(events_out),
            "--output", str(timeline_html)
        ]
        t_res = subprocess.run(t_cmd, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(t_res.returncode, 0, f"Timeline generation failed: {t_res.stderr}")
        self.assertTrue(timeline_html.exists())
        html_content = timeline_html.read_text(encoding="utf-8")
        self.assertIn("홍길동", html_content)
        self.assertIn("이순신", html_content)

    def test_multi_chat_full_export_and_filtering(self):
        account_data = {
            "about": "Telegram Account Export",
            "chats": {
                "list": [
                    {
                        "name": "비밀 프로젝트 방",
                        "type": "group",
                        "id": 999111,
                        "messages": [
                            {
                                "id": 1,
                                "type": "message",
                                "date": "2024-02-01T10:00:00",
                                "from": "김철수",
                                "text": "비트코인 이체 내역 확인 완료되었습니다."
                            },
                            {
                                "id": 2,
                                "type": "message",
                                "date": "2024-02-01T10:05:00",
                                "from": "박영희",
                                "text": "네 회계 장부에 반영하겠습니다."
                            }
                        ]
                    }
                ]
            }
        }
        json_path = self.tmp / "account_export.json"
        json_path.write_text(json.dumps(account_data, ensure_ascii=False), encoding="utf-8")

        events_out = self.tmp / "filtered_events.json"
        cmd = [
            sys.executable, str(PARSER), str(json_path),
            "--keyword", "비트코인",
            "--events-out", str(events_out)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(res.returncode, 0, res.stderr)

        with open(events_out, "r", encoding="utf-8") as f:
            events = json.load(f)
        self.assertEqual(len(events), 1)
        self.assertIn("비트코인", events[0]["description"])
        self.assertEqual(events[0]["actor"], "김철수")


if __name__ == "__main__":
    unittest.main()
