import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http } from "./api/http";
import type { Release, ReleaseRepo } from "./api/types";
import { releaseBlock, releaseKey } from "./screens/Releases";
import { releases } from "./state/data";
import { confirmReq, toastMsg } from "./state/ui";

const repo = (o: Partial<ReleaseRepo> = {}) => ({ repo: "acme/web", name: "web", head: "staging", base: "master", ahead: 3, prs_waiting: 1, last_release: null, open: null, checked_at: null, actions: [], ...o }) as ReleaseRepo;
const rel = (o: Partial<Release> = {}) => ({ id: "r1", repo: "acme/web", stage: "cut", note: null, note_posted_at: null, ...o }) as Release;
const tick = () => new Promise((r) => setTimeout(r, 0));

describe("Releases keys share the buttons' guards", () => {
  let send: ReturnType<typeof vi.spyOn>;
  beforeEach(() => { send = vi.spyOn(http, "send").mockResolvedValue({} as never); toastMsg.value = null; confirmReq.value = null; });
  afterEach(() => { send.mockRestore(); releases.value = null; });

  it("c with no repo selected does not call the API and shows a toast", async () => {
    releases.value = { repos: [], releases: [] };
    expect(releaseKey("c")).toBe(true);
    await tick();
    expect(send).not.toHaveBeenCalled();
    expect(toastMsg.value?.msg).toBe(releaseBlock.cut());
    expect(toastMsg.value?.msg).toBe("No repository with releases");
  });

  it("a real cut asks first and posts only after a yes; a dry run does not ask", async () => {
    releases.value = { repos: [repo()], releases: [] };
    releaseKey("c");
    await tick();
    expect(confirmReq.value?.text).toBe("Cut a release of acme/web?");
    expect(send).not.toHaveBeenCalled();
    confirmReq.value!.resolve(false);
    await tick();
    expect(send).not.toHaveBeenCalled();
    releaseKey("c");
    await tick();
    confirmReq.value!.resolve(true);
    await tick();
    expect(send).toHaveBeenCalledWith("POST", "/api/releases", { repo: "acme/web", dry_run: undefined });
    send.mockClear();
    releaseKey("y");
    await tick();
    expect(confirmReq.value).toBeNull();
    expect(send).toHaveBeenCalledWith("POST", "/api/releases", { repo: "acme/web", dry_run: true });
  });

  it("a release in flight blocks cut with the button's reason", async () => {
    releases.value = { repos: [repo({ open: "r1" })], releases: [rel()] };
    releaseKey("c");
    await tick();
    expect(send).not.toHaveBeenCalled();
    expect(toastMsg.value?.msg).toBe("A release is already in flight for this repository");
  });

  it("G, n, p, e and x say why when there is no release; g is not a release key", async () => {
    releases.value = { repos: [repo()], releases: [] };
    for (const k of ["G", "n", "p", "e", "x"]) {
      toastMsg.value = null;
      releaseKey(k);
      await tick();
      expect(toastMsg.value?.msg, k).toBe("No release yet");
    }
    expect(releaseKey("g")).toBe(false);
    expect(send).not.toHaveBeenCalled();
  });

  it("n refuses once the note is posted", async () => {
    releases.value = { repos: [repo()], releases: [rel({ note: "hi", note_posted_at: "2026-11-12T10:00:00Z" })] };
    releaseKey("n");
    await tick();
    expect(send).not.toHaveBeenCalled();
    expect(toastMsg.value?.msg).toBe("The note is already posted");
  });
});
