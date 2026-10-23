"""ui_feed: ids, 200 cap, 5-newest replay, restart handling, thread safety."""

import threading

import ui_feed

assert ui_feed.after(None) == {"latest": 0, "events": []}
e = ui_feed.add("ev", "T", "B", "#/inbox")
assert e["id"] == 1 and e["tag"] == "aiw-1" and e["ts"].endswith("+00:00")
assert set(e) == {"id", "event", "title", "body", "path", "tag", "ts"}
assert ui_feed.after(None) == {"latest": 1, "events": []}
assert ui_feed.after(5) == {"latest": 1, "events": []}  # restart: after > latest
assert [x["id"] for x in ui_feed.after(0)["events"]] == [1]

for _ in range(204):
    ui_feed.add("ev", "T", "B", "#/inbox")  # 205 total
ids = [x["id"] for x in ui_feed._entries]
assert len(ids) == 200 and ids[0] == 6 and ids[-1] == 205
r = ui_feed.after(0)
assert r["latest"] == 205 and [x["id"] for x in r["events"]] == [201, 202, 203, 204, 205]
assert [x["id"] for x in ui_feed.after(203)["events"]] == [204, 205]
assert ui_feed.after(205)["events"] == []
r["events"][0]["title"] = "mutated"  # copies, not the stored dicts
assert ui_feed.after(200)["events"][0]["title"] == "T"

ts = [threading.Thread(target=lambda: [ui_feed.add("ev", "T", "B", "p") for _ in range(50)]) for _ in range(10)]
[t.start() for t in ts]
[t.join() for t in ts]
assert ui_feed.after(None)["latest"] == 705
assert len({x["id"] for x in ui_feed._entries}) == 200
print("ok test_ui_feed")
