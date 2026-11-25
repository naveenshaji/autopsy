import io
import json
import unittest
from unittest import mock

from autopsy_memory import claude_code, cli, mcp_bridge


def entry(kind, **fields):
    return json.dumps({"type": kind, "sessionId": "s-1", **fields})


TRANSCRIPT = [
    entry("custom-title", customTitle="Dock work"),
    entry("user", uuid="u1", timestamp="2026-11-16T23:40:00.000Z", cwd="/home/me/proj",
          message={"role": "user", "content": "<canvas-thread>\nAttached to: nothing\n</canvas-thread>\n\nMake the dock smaller"}),
    entry("assistant", uuid="a1", timestamp="2026-11-16T23:40:05.000Z", message={"role": "assistant", "content": [
        {"type": "thinking", "thinking": "private"},
        {"type": "text", "text": "Shrinking it."},
        {"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "/home/me/proj/Dock.qml"}},
    ]}),
    entry("user", uuid="r1", timestamp="2026-11-16T23:40:06.000Z", message={"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
    ]}),
    entry("attachment", attachment={"type": "queued_command", "prompt": "and no bounce please"}),
    entry("attachment", attachment={"type": "queued_command", "prompt": "<task-notification>x</task-notification>"}),
    entry("assistant", uuid="a2", timestamp="2026-11-16T23:41:00.000Z", message={"role": "assistant", "content": [
        {"type": "text", "text": "Done: smaller icons, no bounce."},
    ]}),
    entry("user", uuid="m1", isMeta=True, message={"role": "user", "content": "[Image: original 10x10]"}),
    entry("user", uuid="c1", timestamp="2026-11-16T23:50:00.000Z", isCompactSummary=True,
          message={"role": "user", "content": "This session is being continued...\n\nSummary:\nWe shrank the dock."}),
    entry("assistant", uuid="a3", timestamp="2026-11-16T23:51:00.000Z", message={"role": "assistant", "content": [
        {"type": "text", "text": "Continuing after the recap."},
    ]}),
    entry("user", uuid="u2", timestamp="2026-11-17T00:00:00.000Z",
          message={"role": "user", "content": [{"type": "text", "text": "<local-command-stdout>x</local-command-stdout>"}]}),
    "not json",
]


class ClaudeCodeTranscriptTests(unittest.TestCase):
    def setUp(self):
        self.parsed = claude_code.parse_transcript(TRANSCRIPT)

    def test_session_fields(self):
        self.assertEqual(self.parsed["session_id"], "s-1")
        self.assertEqual(self.parsed["title"], "Dock work")
        self.assertEqual(self.parsed["cwd"], "/home/me/proj")
        self.assertEqual(self.parsed["parse_errors"], 1)

    def test_one_exchange_per_human_prompt_plus_recap(self):
        kinds = [(e["uuid"], e["kind"]) for e in self.parsed["exchanges"]]
        self.assertEqual(kinds, [("u1", "exchange"), ("c1", "summary")])

    def test_exchange_keeps_conversation_and_drops_machinery(self):
        exchange = self.parsed["exchanges"][0]
        self.assertEqual(exchange["prompt"], "Make the dock smaller")
        self.assertIn("<canvas-thread>", exchange["context"])
        self.assertIn("User (while Claude worked): and no bounce please", exchange["text"])
        self.assertIn("Done: smaller icons, no bounce.", exchange["text"])
        self.assertIn("Continuing after the recap.", exchange["text"])   # compaction is mid-turn
        self.assertNotIn("private", exchange["text"])
        self.assertNotIn("task-notification", exchange["text"])
        self.assertEqual(exchange["files"], ["/home/me/proj/Dock.qml"])
        self.assertEqual(exchange["tools"], {"Edit": 1})
        self.assertEqual(exchange["ended"], "2026-11-16T23:51:00.000Z")

    def test_recap_keeps_summary_text(self):
        self.assertEqual(self.parsed["exchanges"][1]["prompt"], "We shrank the dock.")

    def test_keys_are_stable_as_transcript_grows(self):
        grown = claude_code.parse_transcript(TRANSCRIPT + [entry("assistant", uuid="a9", timestamp="2026-11-17T00:01:00.000Z",
                                                                  message={"role": "assistant", "content": [{"type": "text", "text": "More."}]})])
        before = {e["uuid"]: e["sha"] for e in self.parsed["exchanges"]}
        after = {e["uuid"]: e["sha"] for e in grown["exchanges"]}
        self.assertEqual(set(before), set(after))
        self.assertNotEqual(before["u1"], after["u1"])     # the live exchange changed
        self.assertEqual(before["c1"], after["c1"])        # the recap did not
        self.assertEqual(claude_code.exchange_stable_key("s-1", "u1"), "claude-session:s-1#u1")

    def test_split_passages_respects_size_and_keeps_text(self):
        text = "\n\n".join(f"Paragraph {n} " + "word " * 60 for n in range(10))
        passages = claude_code.split_passages(text, size=400)
        self.assertGreater(len(passages), 3)
        self.assertTrue(all(len(p) <= 800 for p in passages))
        self.assertEqual("".join(passages).replace("\n", "").replace(" ", ""), text.replace("\n", "").replace(" ", ""))


class RememberHelperTests(unittest.TestCase):
    def test_fulltext_query_drops_stopwords(self):
        self.assertEqual(cli.remember_fulltext_query("What did we decide about the dock?"), "decide|dock")

    def test_embedding_text_skips_summary_that_repeats_body(self):
        text = cli.embedding_text_for_item("Title", "Body starts here…", "Body starts here and goes on")
        self.assertEqual(text, "Title\nBody starts here and goes on")


class McpFramingTests(unittest.TestCase):
    def test_newline_json_is_answered_in_kind(self):
        stdin = io.BytesIO(b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n')
        stdout = io.BytesIO()
        with mock.patch.object(mcp_bridge.sys, "stdin", mock.Mock(buffer=stdin)), \
                mock.patch.object(mcp_bridge.sys, "stdout", mock.Mock(buffer=stdout)):
            message = mcp_bridge.read_message()
            mcp_bridge.write_message({"jsonrpc": "2.0", "id": message["id"], "result": {}})
        self.assertEqual(stdout.getvalue(), b'{"jsonrpc":"2.0","id":1,"result":{}}\n')

    def test_content_length_framing_still_works(self):
        body = b'{"jsonrpc":"2.0","id":2,"method":"ping"}'
        stdin = io.BytesIO(b"Content-Length: %d\r\n\r\n" % len(body) + body)
        stdout = io.BytesIO()
        with mock.patch.object(mcp_bridge.sys, "stdin", mock.Mock(buffer=stdin)), \
                mock.patch.object(mcp_bridge.sys, "stdout", mock.Mock(buffer=stdout)):
            message = mcp_bridge.read_message()
            mcp_bridge.write_message({"id": message["id"]})
        self.assertTrue(stdout.getvalue().startswith(b"Content-Length: "))

    def test_compact_response_is_defined(self):
        self.assertEqual(mcp_bridge.compact_response({"a": [1, "é"]}), '{"a":[1,"é"]}')


def codex(kind, payload, ts="2026-11-18T23:11:49.000Z"):
    return json.dumps({"timestamp": ts, "type": kind, "payload": payload})


class CodexRolloutTests(unittest.TestCase):
    ROLLOUT = [
        codex("session_meta", {"id": "c-1", "cwd": "/home/me/proj", "git": {"branch": "main"}}),
        codex("response_item", {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "rules"}]}),
        codex("response_item", {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "<environment_context>x</environment_context>"}]}),
        codex("response_item", {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Fix the dock"}]}),
        codex("response_item", {"type": "reasoning", "summary": []}),
        codex("response_item", {"type": "custom_tool_call", "name": "apply_patch", "call_id": "1",
                                "input": "*** Begin Patch\n*** Update File: shell/Dock.qml\n@@\n*** End Patch"}),
        codex("response_item", {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Fixed it."}]},
              ts="2026-11-18T23:12:00.000Z"),
    ]

    def test_rollout_becomes_exchanges(self):
        parsed = claude_code.parse_codex_rollout(self.ROLLOUT)
        self.assertEqual(parsed["harness"], "codex")
        self.assertEqual(parsed["session_id"], "c-1")
        self.assertEqual(len(parsed["exchanges"]), 1)
        exchange = parsed["exchanges"][0]
        self.assertIn("User: Fix the dock", exchange["text"])
        self.assertIn("Codex: Fixed it.", exchange["text"])
        self.assertEqual(exchange["files"], ["/home/me/proj/shell/Dock.qml"])
        self.assertEqual(exchange["tools"], {"apply_patch": 1})
        again = claude_code.parse_codex_rollout(self.ROLLOUT)["exchanges"][0]
        self.assertEqual(again["uuid"], exchange["uuid"])   # stable across re-reads

    def test_keys_do_not_collide_with_claude(self):
        self.assertEqual(claude_code.session_stable_key("x", "codex"), "codex-session:x")
        self.assertEqual(claude_code.session_stable_key("x"), "claude-session:x")


if __name__ == "__main__":
    unittest.main()
