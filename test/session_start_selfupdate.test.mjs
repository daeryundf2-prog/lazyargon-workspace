/**
 * test/session_start_selfupdate.test.mjs
 *
 * Tests for autoUpdate() in scripts/session_start.mjs.
 * Uses throwaway local bare-origin + clone repos — no network required.
 * Cases: clean+behind (fast-forward), dirty+behind (notice), up-to-date (silent),
 *        opt-out env, throttle (6 h), non-main branch, fetch failure.
 */
import assert from "node:assert/strict";
import { execSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const { autoUpdate } = await import(path.join(ROOT, "scripts", "session_start.mjs"));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Fake writable stream that collects written strings. */
function makeCapture() {
	const lines = [];
	return {
		write(chunk) {
			lines.push(typeof chunk === "string" ? chunk : chunk.toString());
			return true;
		},
		get text() {
			return lines.join("");
		},
		lines,
	};
}

const GIT_ENV = {
	GIT_AUTHOR_NAME: "Test",
	GIT_AUTHOR_EMAIL: "test@example.com",
	GIT_COMMITTER_NAME: "Test",
	GIT_COMMITTER_EMAIL: "test@example.com",
};

function exec(cmd, cwd) {
	return execSync(cmd, { cwd, stdio: "pipe", env: { ...process.env, ...GIT_ENV } });
}

/**
 * Create a bare origin + a clone in tmp.
 * Returns { origin, clone } absolute paths.
 * The clone:
 *   - is on branch main with origin remote pointing to the bare origin
 */
function setupRepo(tmp) {
	const origin = path.join(tmp, "origin.git");
	const work = path.join(tmp, "work");
	const clone = path.join(tmp, "clone");

	// Bare origin.
	exec(`git init --bare -b main "${origin}"`, tmp);

	// Working copy to seed the origin.
	fs.mkdirSync(work);
	exec(`git init -b main "${work}"`, tmp);
	exec(`git -C "${work}" config user.email "test@example.com"`, tmp);
	exec(`git -C "${work}" config user.name "Test"`, tmp);
	fs.writeFileSync(path.join(work, "README.md"), "init\n", "utf8");
	exec(`git -C "${work}" add .`, tmp);
	exec(`git -C "${work}" commit -m "init"`, tmp);
	exec(`git -C "${work}" remote add origin "${origin}"`, tmp);
	exec(`git -C "${work}" push origin main`, tmp);

	// Clone from bare origin.
	exec(`git clone "${origin}" "${clone}"`, tmp);
	exec(`git -C "${clone}" config user.email "test@example.com"`, tmp);
	exec(`git -C "${clone}" config user.name "Test"`, tmp);

	return { origin, clone, work };
}

/** Push a new commit to the bare origin via the work checkout. */
function pushNewCommit(work, message = "upstream") {
	const fname = `file-${Date.now()}.txt`;
	fs.writeFileSync(path.join(work, fname), `${message}\n`, "utf8");
	exec(`git -C "${work}" add .`, work);
	exec(`git -C "${work}" commit -m "${message}"`, work);
	exec(`git -C "${work}" push origin main`, work);
}

// ---------------------------------------------------------------------------
// Test cases
// ---------------------------------------------------------------------------

test("clean+behind: fast-forwards and prints one update line", () => {
	const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "la-upd-clean-"));
	try {
		const { work, clone } = setupRepo(tmp);
		pushNewCommit(work, "upstream-commit-1");

		const cap = makeCapture();
		autoUpdate(clone, {}, cap);

		// Clone HEAD should now equal origin/main.
		const cloneHead = exec(`git -C "${clone}" rev-parse HEAD`, clone).toString().trim();
		const originHead = exec(`git -C "${clone}" rev-parse origin/main`, clone).toString().trim();
		assert.equal(cloneHead, originHead, "clone was fast-forwarded to origin/main");

		assert.equal(cap.lines.length, 1, "exactly one line written");
		assert.match(
			cap.lines[0],
			/^LazyArgon Workspace updated [0-9a-f]{7}\.\.[0-9a-f]{7} \(1 commits?\)\n$/,
			"update line matches expected format",
		);
	} finally {
		fs.rmSync(tmp, { recursive: true, force: true });
	}
});

test("dirty+behind: leaves files untouched and prints notice", () => {
	const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "la-upd-dirty-"));
	try {
		const { work, clone } = setupRepo(tmp);
		pushNewCommit(work, "upstream-commit-2");

		// Dirty the clone working tree (tracked file, unstaged change).
		fs.appendFileSync(path.join(clone, "README.md"), "local change\n", "utf8");

		const headBefore = exec(`git -C "${clone}" rev-parse HEAD`, clone).toString().trim();
		const readmeBefore = fs.readFileSync(path.join(clone, "README.md"), "utf8");

		const cap = makeCapture();
		autoUpdate(clone, {}, cap);

		// HEAD must be unchanged.
		const headAfter = exec(`git -C "${clone}" rev-parse HEAD`, clone).toString().trim();
		assert.equal(headAfter, headBefore, "HEAD was not moved");

		// Local file must be unchanged.
		assert.equal(
			fs.readFileSync(path.join(clone, "README.md"), "utf8"),
			readmeBefore,
			"README.md was not modified",
		);

		assert.equal(cap.lines.length, 1, "exactly one line written");
		assert.match(cap.lines[0], /local changes present, not auto-updated/, "notice includes 'local changes present'");
		assert.match(cap.lines[0], /git -C .+ stash/, "notice includes stash instruction");
	} finally {
		fs.rmSync(tmp, { recursive: true, force: true });
	}
});

test("up to date: completely silent", () => {
	const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "la-upd-utd-"));
	try {
		const { clone } = setupRepo(tmp);

		const cap = makeCapture();
		autoUpdate(clone, {}, cap);

		assert.equal(cap.lines.length, 0, "no output when up to date");
	} finally {
		fs.rmSync(tmp, { recursive: true, force: true });
	}
});

test("LAZYARGON_WORKSPACE_NO_AUTO_UPDATE=1: skips entirely with no git calls", () => {
	const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "la-upd-optout-"));
	try {
		const { origin, work, clone } = setupRepo(tmp);
		pushNewCommit(work, "upstream-commit-optout");

		const cap = makeCapture();
		autoUpdate(clone, { LAZYARGON_WORKSPACE_NO_AUTO_UPDATE: "1" }, cap);

		// No output.
		assert.equal(cap.lines.length, 0, "no output when opted out");

		// Clone still at old commit — merge was NOT performed.
		// Compare against bare origin's actual HEAD (not clone's cached origin/main ref,
		// which is also at the old commit because we never fetched).
		const cloneHead = exec(`git -C "${clone}" rev-parse HEAD`, clone).toString().trim();
		const bareOriginHead = exec(`git -C "${origin}" rev-parse HEAD`, tmp).toString().trim();
		assert.notEqual(cloneHead, bareOriginHead, "clone was NOT fast-forwarded to upstream");
	} finally {
		fs.rmSync(tmp, { recursive: true, force: true });
	}
});

test("throttle: second call within 6 h does not fetch", () => {
	const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "la-upd-throttle-"));
	try {
		const { origin, work, clone } = setupRepo(tmp);
		pushNewCommit(work, "upstream-commit-throttle");

		// First call: should update.
		const cap1 = makeCapture();
		autoUpdate(clone, {}, cap1);
		assert.equal(cap1.lines.length, 1, "first call updates");

		// Push another commit upstream — clone won't get it if throttled.
		pushNewCommit(work, "upstream-commit-throttle-2");

		// Second call within 6 h (state file just written): must skip.
		const cap2 = makeCapture();
		autoUpdate(clone, {}, cap2);
		assert.equal(cap2.lines.length, 0, "second call within 6 h is silent");

		// Clone should NOT have the second commit.
		// Compare against bare origin's actual HEAD (which now has commit2).
		const cloneHead = exec(`git -C "${clone}" rev-parse HEAD`, clone).toString().trim();
		const bareOriginHead = exec(`git -C "${origin}" rev-parse HEAD`, tmp).toString().trim();
		assert.notEqual(cloneHead, bareOriginHead, "clone was not updated on the second (throttled) call");
	} finally {
		fs.rmSync(tmp, { recursive: true, force: true });
	}
});

test("non-main branch: skips entirely", () => {
	const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "la-upd-branch-"));
	try {
		const { origin, work, clone } = setupRepo(tmp);
		pushNewCommit(work, "upstream-commit-branch");

		// Switch clone to a different branch before autoUpdate runs.
		exec(`git -C "${clone}" checkout -b feat/something`, clone);

		const cap = makeCapture();
		autoUpdate(clone, {}, cap);

		assert.equal(cap.lines.length, 0, "no output when not on main");

		// Clone's main was not updated — verify against bare origin's actual HEAD.
		exec(`git -C "${clone}" checkout main`, clone);
		const cloneHead = exec(`git -C "${clone}" rev-parse HEAD`, clone).toString().trim();
		const bareOriginHead = exec(`git -C "${origin}" rev-parse HEAD`, tmp).toString().trim();
		assert.notEqual(cloneHead, bareOriginHead, "clone main was not updated when on a different branch");
	} finally {
		fs.rmSync(tmp, { recursive: true, force: true });
	}
});

test("fetch failure: silent, no exception, exit-safe", () => {
	const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "la-upd-fetchfail-"));
	try {
		const { clone } = setupRepo(tmp);

		// Point origin at a non-existent path to simulate network/fetch failure.
		exec(`git -C "${clone}" remote set-url origin "/nonexistent-path-${Date.now()}"`, clone);

		const cap = makeCapture();
		// Must not throw and must remain silent.
		assert.doesNotThrow(() => autoUpdate(clone, {}, cap));
		assert.equal(cap.lines.length, 0, "no output on fetch failure");
	} finally {
		fs.rmSync(tmp, { recursive: true, force: true });
	}
});

/** Expire the throttle stamp so the next call checks again. */
function expireThrottle(clone) {
	const stamp = path.join(clone, ".git", "lazyargon-workspace-last-update-check");
	fs.writeFileSync(stamp, String(Date.now() - 7 * 60 * 60 * 1000), "utf8");
}

test("throttle stamp never dirties the tree: a later check still fast-forwards", () => {
	const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "la-upd-stamp-"));
	try {
		const { work, clone } = setupRepo(tmp);
		pushNewCommit(work, "first");
		autoUpdate(clone, {}, makeCapture());
		assert.equal(exec(`git -C "${clone}" status --porcelain`, clone).toString(), "", "tree clean after a check");

		pushNewCommit(work, "second");
		expireThrottle(clone);
		const cap = makeCapture();
		autoUpdate(clone, {}, cap);
		assert.equal(cap.lines.length, 1);
		assert.match(cap.lines[0], /^LazyArgon Workspace updated /);
	} finally {
		fs.rmSync(tmp, { recursive: true, force: true });
	}
});

test("only local commits ahead, nothing new upstream: silent", () => {
	const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "la-upd-ahead-"));
	try {
		const { clone } = setupRepo(tmp);
		fs.writeFileSync(path.join(clone, "local.txt"), "mine\n", "utf8");
		exec(`git -C "${clone}" add . && git -C "${clone}" commit -m local`, clone);
		const cap = makeCapture();
		autoUpdate(clone, {}, cap);
		assert.equal(cap.lines.length, 0);
	} finally {
		fs.rmSync(tmp, { recursive: true, force: true });
	}
});

test("diverged (local commit + upstream commit): no merge, notice names local commits", () => {
	const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "la-upd-diverged-"));
	try {
		const { work, clone } = setupRepo(tmp);
		fs.writeFileSync(path.join(clone, "local.txt"), "mine\n", "utf8");
		exec(`git -C "${clone}" add . && git -C "${clone}" commit -m local`, clone);
		const before = exec(`git -C "${clone}" rev-parse HEAD`, clone).toString().trim();
		pushNewCommit(work, "upstream");
		const cap = makeCapture();
		autoUpdate(clone, {}, cap);
		assert.equal(exec(`git -C "${clone}" rev-parse HEAD`, clone).toString().trim(), before, "HEAD unchanged");
		assert.equal(cap.lines.length, 1);
		assert.match(cap.lines[0], /local commits differ, not auto-updated/);
	} finally {
		fs.rmSync(tmp, { recursive: true, force: true });
	}
});
