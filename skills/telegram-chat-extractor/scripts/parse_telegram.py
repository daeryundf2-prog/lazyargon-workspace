#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_telegram.py
Parse Telegram Desktop chat exports (JSON result.json).

Features:
- Handles single chat export and full account multi-chat exports.
- Flattens nested rich text entities (links, mentions, formatting).
- Extracts service events, media attachments, forwarded sources, and reply chains.
- Outputs structured JSON, summary analytics, and timeline events for generate_timeline.py.
"""

import argparse
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _flatten_text(text_val):
    if isinstance(text_val, str):
        return text_val.strip()
    if isinstance(text_val, list):
        parts = []
        for item in text_val:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get("text", ""))
        return "".join(parts).strip()
    return ""


def _extract_attachments(msg):
    attachments = []
    if msg.get("photo"):
        attachments.append({
            "type": "photo",
            "file": msg.get("photo"),
            "width": msg.get("width"),
            "height": msg.get("height")
        })
    if msg.get("file"):
        attachments.append({
            "type": msg.get("media_type", "file"),
            "file": msg.get("file"),
            "mime_type": msg.get("mime_type"),
            "duration_seconds": msg.get("duration_seconds")
        })
    if msg.get("sticker_emoji"):
        attachments.append({
            "type": "sticker",
            "emoji": msg.get("sticker_emoji"),
            "file": msg.get("file")
        })
    return attachments


def parse_telegram_json_data(raw_data):
    chats = []
    if "chats" in raw_data and isinstance(raw_data["chats"], dict):
        chat_list = raw_data["chats"].get("list", [])
        for c in chat_list:
            chats.append(_process_single_chat(c))
    elif "messages" in raw_data:
        chats.append(_process_single_chat(raw_data))
    else:
        raise ValueError("Invalid Telegram JSON: no messages or chats.list structure found")
    return chats


def _process_single_chat(chat_obj):
    chat_name = chat_obj.get("name", "Unknown Chat")
    chat_type = chat_obj.get("type", "unknown")
    chat_id = chat_obj.get("id")
    messages = []
    participants = {}
    attachment_counts = {}
    service_event_count = 0

    for msg in chat_obj.get("messages", []):
        msg_id = msg.get("id")
        msg_type = msg.get("type", "message")
        date_str = msg.get("date", "")
        sender = msg.get("from", msg.get("actor", "Unknown"))
        sender_id = msg.get("from_id", msg.get("actor_id", ""))
        text_content = _flatten_text(msg.get("text", msg.get("action", "")))
        attachments = _extract_attachments(msg)

        if msg_type == "service":
            service_event_count += 1
        elif sender:
            participants[sender] = participants.get(sender, 0) + 1

        for att in attachments:
            t = att.get("type", "file")
            attachment_counts[t] = attachment_counts.get(t, 0) + 1

        rec = {
            "id": msg_id,
            "type": msg_type,
            "date": date_str,
            "sender": sender,
            "sender_id": sender_id,
            "text": text_content,
            "reply_to_message_id": msg.get("reply_to_message_id"),
            "forwarded_from": msg.get("forwarded_from"),
            "edited": msg.get("edited"),
            "attachments": attachments,
            "has_attachment": len(attachments) > 0
        }
        messages.append(rec)

    first_date = messages[0]["date"] if messages else None
    last_date = messages[-1]["date"] if messages else None
    return {
        "chat_name": chat_name,
        "chat_type": chat_type,
        "chat_id": chat_id,
        "total_messages": len(messages),
        "service_event_count": service_event_count,
        "date_range": {"first": first_date, "last": last_date},
        "participants": participants,
        "attachment_counts": attachment_counts,
        "messages": messages
    }


def convert_to_timeline_events(chats, keyword_filter=None, sender_filter=None):
    events = []
    for chat in chats:
        c_name = chat["chat_name"]
        for msg in chat["messages"]:
            date_val = msg.get("date")
            if not date_val:
                continue
            text = msg.get("text", "")
            sender = msg.get("sender", "Unknown")
            if keyword_filter and keyword_filter.lower() not in text.lower():
                continue
            if sender_filter and sender_filter.lower() not in sender.lower():
                continue
            normalized_date = date_val.replace(" ", "T")
            desc = f"{sender}: {text}" if text else f"{sender}: [Attachment/Media]"
            if msg.get("forwarded_from"):
                desc += f" (Forwarded: {msg['forwarded_from']})"
            att_info = ""
            if msg.get("attachments"):
                att_info = ", ".join(a.get("type", "file") for a in msg["attachments"])
            details_str = f"Chat: {c_name} | ID: {msg.get('id')}"
            if att_info:
                details_str += f" | Attachments: {att_info}"
            events.append({
                "timestamp": normalized_date,
                "category": "chat",
                "source": "Telegram",
                "actor": sender,
                "description": desc,
                "details": details_str
            })
    return events


def main():
    parser = argparse.ArgumentParser(description="Telegram Chat Export (JSON) Forensic Parser")
    parser.add_argument("input_file", help="Path to Telegram export file (result.json)")
    parser.add_argument("--output", "-o", help="Path to output JSON")
    parser.add_argument("--events-out", help="Path to output standard timeline events JSON for generate_timeline.py")
    parser.add_argument("--keyword", "-k", help="Filter messages by keyword")
    parser.add_argument("--sender", "-s", help="Filter messages by sender")
    parser.add_argument("--summary", action="store_true", help="Print summary statistics to stdout")
    args = parser.parse_args()
    input_path = os.path.abspath(args.input_file)
    if not os.path.exists(input_path):
        print(f"[-] File not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    try:
        with open(input_path, "r", encoding="utf-8", errors="replace") as f:
            raw_json = json.load(f)
        chats = parse_telegram_json_data(raw_json)
    except Exception as e:
        print(f"[-] Failed to parse Telegram export: {e}", file=sys.stderr)
        sys.exit(1)
    if args.keyword or args.sender:
        for c in chats:
            filtered = []
            for m in c["messages"]:
                if args.keyword and args.keyword.lower() not in m.get("text", "").lower():
                    continue
                if args.sender and args.sender.lower() not in m.get("sender", "").lower():
                    continue
                filtered.append(m)
            c["messages"] = filtered
            c["total_messages"] = len(filtered)
    if args.events_out:
        events = convert_to_timeline_events(chats, args.keyword, args.sender)
        os.makedirs(os.path.dirname(os.path.abspath(args.events_out)) or ".", exist_ok=True)
        with open(args.events_out, "w", encoding="utf-8") as f:
            json.dump(events, f, ensure_ascii=False, indent=2)
        print(f"[+] Timeline events ({len(events)} events) saved to: {args.events_out}")
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(chats, f, ensure_ascii=False, indent=2)
        print(f"[+] Parsed Telegram data saved to: {args.output}")
    if args.summary or (not args.output and not args.events_out):
        print("\n=== 📱 Telegram Export Forensic Summary ===")
        for i, c in enumerate(chats, 1):
            print(f"[{i}] Chat: {c['chat_name']} ({c['chat_type']})")
            print(f"    - Total Messages: {c['total_messages']:,} msgs (Service Events: {c['service_event_count']:,})")
            print(f"    - Date Range: {c['date_range']['first']} ~ {c['date_range']['last']}")
            print("    - Top Participants:")
            sorted_part = sorted(c['participants'].items(), key=lambda x: x[1], reverse=True)[:5]
            for name, count in sorted_part:
                print(f"      • {name}: {count:,} msgs")
            if c['attachment_counts']:
                print(f"    - Attachments: {c['attachment_counts']}")
        print("===========================================\n")


if __name__ == "__main__":
    main()
