"use client";

import { useState } from "react";
import type { ActorSummary } from "@forge/shared-types";
import { getDemoToken, getMe } from "../lib/api";

type DemoSubject = "alice" | "bob" | "mallory";

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
    <main>
      <div className="shell">
        <section>
          <p className="muted">Forge AI control plane</p>
          <h1>Identity, tenant isolation, and workspace access</h1>
        </section>

        <section className="panel">
          <div className="row">
            <button
              className={selected === "alice" ? "primary" : ""}
              onClick={() => void loadIdentity("alice")}
            >
              Alice Admin
            </button>
            <button
              className={selected === "bob" ? "primary" : ""}
              onClick={() => void loadIdentity("bob")}
            >
              Bob Viewer
            </button>
            <button
              className={selected === "mallory" ? "primary" : ""}
              onClick={() => void loadIdentity("mallory")}
            >
              Mallory Outsider
            </button>
          </div>
          <p>{status}</p>
          {error ? <p className="error">{error}</p> : null}
        </section>

        {actor ? (
          <section className="panel">
            <h2>{actor.display_name}</h2>
            <p className="muted">{actor.email}</p>
            <div className="workspace-grid">
              {actor.workspaces.map((workspace) => (
                <article className="workspace" key={workspace.id}>
                  <h3>{workspace.name}</h3>
                  <p className="muted">Role: {workspace.role}</p>
                  <div className="capabilities">
                    {workspace.capabilities.map((capability) => (
                      <span className="capability" key={capability}>
                        {capability}
                      </span>
                    ))}
                  </div>
                </article>
              ))}
              {actor.workspaces.length === 0 ? (
                <article className="workspace">
                  <h3>No accessible workspaces</h3>
                  <p className="muted">The API returned no tenant-scoped memberships.</p>
                </article>
              ) : null}
            </div>
          </section>
        ) : null}
      </div>
    </main>
  );
}
