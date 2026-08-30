"use client";

import { useState } from "react";
import type { ActorSummary } from "@forge/shared-types";
import { getDemoToken, getMe } from "../lib/api";

type DemoSubject = "alice" | "bob" | "mallory";

const buttonBase =
  "cursor-pointer rounded-full border border-zinc-800 bg-[#0d0d0f] px-3.5 py-2 text-sm font-medium text-zinc-100 transition duration-150 hover:-translate-y-0.5 hover:border-zinc-700 hover:bg-[#141417]";
const activeButton =
  "border-[#58a6ff] bg-gradient-to-br from-[#58a6ff] to-blue-600 text-white shadow-[0_0_0_1px_rgba(88,166,255,0.22),0_12px_28px_rgba(37,99,235,0.22)]";

export default function Home() {
  const [actor, setActor] = useState<ActorSummary | null>(null);
  const [selected, setSelected] = useState<DemoSubject>("alice");
  const [status, setStatus] = useState("Choose a local demo identity.");
  const [error, setError] = useState("");

  async function loadIdentity(subject: DemoSubject) {
    setSelected(subject);
    setError("");
    setStatus("Loading signed local token and workspace scope...");
    try {
      const token = await getDemoToken(subject);
      const me = await getMe(token);
      setActor(me);
      setStatus("Authenticated through the local OIDC/JWKS path.");
    } catch (caught) {
      setActor(null);
      setError(caught instanceof Error ? caught.message : "Unknown error");
      setStatus("Identity request failed safely.");
    }
  }

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_20%_0%,rgba(88,166,255,0.14),transparent_32rem),linear-gradient(180deg,#09090b_0%,#050505_44%)] px-6 py-8">
      <div className="mx-auto grid max-w-5xl gap-4">
        <section>
          <p className="text-sm text-zinc-400">Forge AI control plane</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-zinc-50">
            Identity, tenant isolation, and workspace access
          </h1>
        </section>

        <section className="rounded-[18px] border border-zinc-800 bg-[#0d0d0f]/90 p-4 shadow-[0_18px_60px_rgba(0,0,0,0.24)]">
          <div className="flex flex-wrap items-center gap-3">
            <button
              className={`${buttonBase} ${selected === "alice" ? activeButton : ""}`}
              onClick={() => void loadIdentity("alice")}
            >
              Alice Admin
            </button>
            <button
              className={`${buttonBase} ${selected === "bob" ? activeButton : ""}`}
              onClick={() => void loadIdentity("bob")}
            >
              Bob Viewer
            </button>
            <button
              className={`${buttonBase} ${selected === "mallory" ? activeButton : ""}`}
              onClick={() => void loadIdentity("mallory")}
            >
              Mallory Outsider
            </button>
          </div>
          <p className="mt-4 text-sm text-zinc-200">{status}</p>
          {error ? <p className="mt-2 whitespace-pre-wrap text-sm text-rose-400">{error}</p> : null}
        </section>

        {actor ? (
          <section className="rounded-[18px] border border-zinc-800 bg-[#0d0d0f]/90 p-4 shadow-[0_18px_60px_rgba(0,0,0,0.24)]">
            <h2 className="text-xl font-semibold text-zinc-50">{actor.display_name}</h2>
            <p className="mt-2 text-sm text-zinc-400">{actor.email}</p>
            <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-[repeat(auto-fit,minmax(260px,1fr))]">
              {actor.workspaces.map((workspace) => (
                <article
                  className="rounded-2xl border border-zinc-800 bg-[#141417] p-4"
                  key={workspace.id}
                >
                  <h3 className="font-semibold text-zinc-50">{workspace.name}</h3>
                  <p className="mt-3 text-sm text-zinc-400">Role: {workspace.role}</p>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {workspace.capabilities.map((capability) => (
                      <span
                        className="rounded-full border border-[#58a6ff]/25 bg-[#58a6ff]/10 px-2 py-1 text-xs text-blue-200"
                        key={capability}
                      >
                        {capability}
                      </span>
                    ))}
                  </div>
                </article>
              ))}
              {actor.workspaces.length === 0 ? (
                <article className="rounded-2xl border border-zinc-800 bg-[#141417] p-4">
                  <h3 className="font-semibold text-zinc-50">No accessible workspaces</h3>
                  <p className="mt-3 text-sm text-zinc-400">
                    The API returned no tenant-scoped memberships.
                  </p>
                </article>
              ) : null}
            </div>
          </section>
        ) : null}
      </div>
    </main>
  );
}
