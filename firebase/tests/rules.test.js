// Security-rule tests (spec §17.4, §40.6). Requires: docker compose up emulators
import { readFileSync } from "node:fs";
import { after, before, beforeEach, describe, test } from "node:test";

import { assertFails, assertSucceeds, initializeTestEnvironment } from "@firebase/rules-unit-testing";
import { doc, getDoc, setDoc } from "firebase/firestore";
import { get, ref, set, update } from "firebase/database";
import { getBytes, ref as storageRef } from "firebase/storage";

const host = process.env.EMULATOR_HOST ?? "127.0.0.1";
const DB_NS = "demo-oltivra-live-00";
let env;

before(async () => {
  env = await initializeTestEnvironment({
    projectId: "demo-oltivra",
    firestore: { host, port: 8080, rules: readFileSync("../firestore.rules", "utf8") },
    database: { host, port: 9000, rules: readFileSync("../rtdb/live-shard.rules.json", "utf8") },
    storage: { host, port: 9199, rules: readFileSync("../storage.rules", "utf8") },
  });
});

after(async () => env?.cleanup());

beforeEach(async () => {
  await env.clearFirestore();
  await env.clearDatabase();
  await env.withSecurityRulesDisabled(async (ctx) => {
    const fs = ctx.firestore();
    await setDoc(doc(fs, "users/alice"), { mmr: 1100, username_normalized: "alice" });
    await setDoc(doc(fs, "public_profiles/alice"), { username_display: "alice" });
    await setDoc(doc(fs, "question_private/q1_3"), { correct_concept_id: "italy" });
    await setDoc(doc(fs, "question_translations/q1_en_3"), { question_text: "?" });
    await setDoc(doc(fs, "match_index/m1"), { participant_uids: ["alice", "bob"], rtdb_shard_id: "live-00" });
    await setDoc(doc(fs, "user_runtime/alice"), { state: "IDLE" });
    await setDoc(doc(fs, "parties/p1"), { host_uid: "alice", invited_uids: ["bob"] });
    await setDoc(doc(fs, "server_config/active"), { config_version: 1 });
    const db = ctx.database(`http://${host}:9000?ns=${DB_NS}`);
    await set(ref(db, "matches/m1"), {
      public: { state: "ROUND_ACTIVE", state_version: 3 },
      player_private: { alice: { option_order: { A: "italy" } }, bob: { option_order: { A: "spain" } } },
      authoritative: { round: { correct_concept_id: "italy" } },
      access: { alice: "participant", bob: "participant", carol: "spectator" },
    });
  });
});

const fsAs = (uid) => (uid ? env.authenticatedContext(uid) : env.unauthenticatedContext()).firestore();
const dbAs = (uid) =>
  (uid ? env.authenticatedContext(uid) : env.unauthenticatedContext()).database(`http://${host}:9000?ns=${DB_NS}`);

describe("firestore", () => {
  test("users (with MMR) are never client readable", async () => {
    await assertFails(getDoc(doc(fsAs("alice"), "users/alice")));
  });
  test("private answers and translations are server only", async () => {
    await assertFails(getDoc(doc(fsAs("alice"), "question_private/q1_3")));
    await assertFails(getDoc(doc(fsAs("alice"), "question_translations/q1_en_3")));
  });
  test("server config is server only", async () => {
    await assertFails(getDoc(doc(fsAs("alice"), "server_config/active")));
  });
  test("public profiles readable when signed in only", async () => {
    await assertSucceeds(getDoc(doc(fsAs("bob"), "public_profiles/alice")));
    await assertFails(getDoc(doc(fsAs(null), "public_profiles/alice")));
  });
  test("no client writes anywhere", async () => {
    await assertFails(setDoc(doc(fsAs("alice"), "public_profiles/alice"), { username_display: "x" }));
    await assertFails(setDoc(doc(fsAs("alice"), "users/alice"), { mmr: 9999 }));
    await assertFails(setDoc(doc(fsAs("alice"), "user_runtime/alice"), { state: "IDLE" }));
  });
  test("match index only for participants", async () => {
    await assertSucceeds(getDoc(doc(fsAs("bob"), "match_index/m1")));
    await assertFails(getDoc(doc(fsAs("mallory"), "match_index/m1")));
  });
  test("runtime pointer only for owner", async () => {
    await assertSucceeds(getDoc(doc(fsAs("alice"), "user_runtime/alice")));
    await assertFails(getDoc(doc(fsAs("bob"), "user_runtime/alice")));
  });
  test("party readable by host and invitees", async () => {
    await assertSucceeds(getDoc(doc(fsAs("bob"), "parties/p1")));
    await assertFails(getDoc(doc(fsAs("mallory"), "parties/p1")));
  });
});

describe("rtdb live shard", () => {
  test("participant reads public", async () => {
    await assertSucceeds(get(ref(dbAs("alice"), "matches/m1/public")));
  });
  test("spectator reads public but no private", async () => {
    await assertSucceeds(get(ref(dbAs("carol"), "matches/m1/public")));
    await assertFails(get(ref(dbAs("carol"), "matches/m1/player_private/carol")));
  });
  test("nonparticipant cannot read the match", async () => {
    await assertFails(get(ref(dbAs("mallory"), "matches/m1/public")));
    await assertFails(get(ref(dbAs(null), "matches/m1/public")));
  });
  test("participant reads only own private projection", async () => {
    await assertSucceeds(get(ref(dbAs("alice"), "matches/m1/player_private/alice")));
    await assertFails(get(ref(dbAs("alice"), "matches/m1/player_private/bob")));
  });
  test("nobody reads authoritative or access", async () => {
    await assertFails(get(ref(dbAs("alice"), "matches/m1/authoritative")));
    await assertFails(get(ref(dbAs("alice"), "matches/m1/access")));
    await assertFails(get(ref(dbAs("alice"), "matches/m1")));
  });
  test("clients cannot write state, score or private data", async () => {
    await assertFails(update(ref(dbAs("alice"), "matches/m1/public"), { state: "FINISHED" }));
    await assertFails(set(ref(dbAs("alice"), "matches/m1/public/participants/alice/score"), 99));
    await assertFails(set(ref(dbAs("alice"), "matches/m1/player_private/alice/own_answer_status"), "ANSWERED_CORRECT"));
    await assertFails(set(ref(dbAs("alice"), "matches/m1/authoritative/round"), {}));
  });
  test("presence write limited to own small safe payload", async () => {
    await assertSucceeds(set(ref(dbAs("alice"), "matches/m1/presence/alice"), { ts: Date.now(), state: "online" }));
    await assertFails(set(ref(dbAs("alice"), "matches/m1/presence/bob"), { ts: Date.now(), state: "online" }));
    await assertFails(set(ref(dbAs("alice"), "matches/m1/presence/alice"), { ts: Date.now(), state: "online", score: 5 }));
    await assertFails(set(ref(dbAs("mallory"), "matches/m1/presence/mallory"), { ts: Date.now(), state: "online" }));
  });
});

describe("storage", () => {
  test("question media is not directly readable", async () => {
    await env.withSecurityRulesDisabled(async (ctx) => {
      const { uploadString } = await import("firebase/storage");
      await uploadString(storageRef(ctx.storage(), "questions/g1/v3/main.webp"), "x");
      await uploadString(storageRef(ctx.storage(), "avatars/av_001.webp"), "x");
    });
    const alice = env.authenticatedContext("alice").storage();
    await assertFails(getBytes(storageRef(alice, "questions/g1/v3/main.webp")));
    await assertSucceeds(getBytes(storageRef(alice, "avatars/av_001.webp")));
  });
});
