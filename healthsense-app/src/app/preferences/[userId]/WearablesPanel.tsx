"use client";

import { useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import type { WearableProviderState } from "@/lib/api";

type WearablesPanelProps = {
  userId: string;
  providers: WearableProviderState[];
  initialMessage?: string | null;
  initialStatus?: string | null;
};

function availabilityLabel(value: string | undefined) {
  switch (String(value || "").trim().toLowerCase()) {
    case "ready":
      return "Ready";
    case "config_required":
      return "Needs config";
    case "coming_soon":
      return "Coming soon";
    case "pending_partnership":
      return "Pending access";
    case "requires_app":
      return "Requires app";
    case "disabled":
      return "Disabled";
    default:
      return "Planned";
  }
}

function connectionLabel(provider: WearableProviderState) {
  if (provider.connected) return "Connected";
  const status = String(provider.status || "").trim().toLowerCase();
  if (status === "running") return "Syncing";
  if (status === "disconnected") return "Not connected";
  return status ? `${status.charAt(0).toUpperCase()}${status.slice(1)}` : "Not connected";
}

function formatDate(value: string | null | undefined) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date);
}

export default function WearablesPanel({
  userId,
  providers,
  initialMessage = null,
  initialStatus = null,
}: WearablesPanelProps) {
  const router = useRouter();
  const firstProviderKey = String(providers[0]?.provider || "").trim().toLowerCase();
  const [selectedProvider, setSelectedProvider] = useState(firstProviderKey);
  const [pendingProvider, setPendingProvider] = useState<string | null>(null);
  const [message, setMessage] = useState(initialMessage);
  const [messageTone, setMessageTone] = useState(
    String(initialStatus || "").trim().toLowerCase() === "failed" ? "error" : "info",
  );
  const [isRefreshing, startTransition] = useTransition();
  const activeProvider = useMemo(() => {
    const selected = providers.find(
      (provider) => String(provider.provider || "").trim().toLowerCase() === selectedProvider,
    );
    return selected || providers[0] || null;
  }, [providers, selectedProvider]);

  const runAction = async (
    provider: string | undefined,
    action: "connect" | "disconnect" | "sync",
  ) => {
    const key = String(provider || "").trim().toLowerCase();
    if (!key) return;
    setPendingProvider(key);
    try {
      const res = await fetch(`/api/wearables/${key}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userId,
          redirect_path: `/preferences/${userId}/wearables`,
        }),
      });
      const data = (await res.json().catch(() => ({}))) as {
        error?: string;
        message?: string;
        auth_url?: string;
        provider?: string;
      };
      if (!res.ok) {
        throw new Error(String(data.error || data.message || `Failed to ${action} ${key}`));
      }
      if (action === "connect") {
        const authUrl = String(data.auth_url || "").trim();
        if (!authUrl) {
          throw new Error("Connect URL missing from wearable response.");
        }
        window.location.assign(authUrl);
        return;
      }
      setMessage(
        action === "disconnect"
          ? `${String(data.provider || key).toUpperCase()} disconnected.`
          : `${String(data.provider || key).toUpperCase()} sync queued.`,
      );
      setMessageTone("info");
      startTransition(() => {
        router.refresh();
      });
    } catch (error) {
      const nextMessage = error instanceof Error ? error.message : String(error);
      setMessage(nextMessage);
      setMessageTone("error");
    } finally {
      setPendingProvider(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <h2 className="text-base font-semibold">Wearables</h2>
        <p className="text-[13px] text-[#6b6257]">
          Connect a wearable source so recovery, sleep, and training signals can feed into coaching.
        </p>
      </div>

      {message ? (
        <div
          className={
            messageTone === "error"
              ? "rounded-2xl border border-[#f0c7c0] bg-[#fff1ee] px-4 py-3 text-[13px] text-[#8b3a2d]"
              : "rounded-2xl border border-[#d7efe7] bg-[#f4fbf8] px-4 py-3 text-[13px] text-[#285b4a]"
          }
        >
          {message}
        </div>
      ) : null}

      {!providers.length ? (
        <div className="rounded-2xl border border-[#efe7db] bg-[#fdfaf4] p-4 text-[13px] text-[#6b6257]">
          No wearable sources are available yet.
        </div>
      ) : (
        <>
          <div className="rounded-2xl border border-[#efe7db] bg-[#fdfaf4] p-3">
            <label className="text-[11px] uppercase tracking-[0.18em] text-[#6b6257]">Wearable source</label>
            <select
              className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-[13px]"
              value={String(activeProvider?.provider || "").trim().toLowerCase()}
              onChange={(event) => setSelectedProvider(event.target.value)}
            >
              {providers.map((provider) => {
                const key = String(provider.provider || "").trim().toLowerCase();
                return (
                  <option key={key} value={key}>
                    {provider.label || provider.provider || "Wearable"} - {connectionLabel(provider)}
                  </option>
                );
              })}
            </select>
          </div>

          {activeProvider ? (() => {
            const provider = activeProvider;
            const key = String(provider.provider || "").trim().toLowerCase();
            const isBusy = pendingProvider === key;
            const canConnect = Boolean(provider.connectable) && !provider.connected;
            const canDisconnect = Boolean(provider.connected);
            const canSync = Boolean(provider.connected && provider.sync_supported);
            return (
              <div className="rounded-2xl border border-[#efe7db] bg-[#fdfaf4] p-4 shadow-[0_20px_60px_-55px_rgba(30,27,22,0.45)]">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-base font-semibold text-[#1e1b16]">
                        {provider.label || provider.provider || "Wearable"}
                      </h3>
                      <span className="rounded-full border border-[#efe7db] bg-white px-3 py-1 text-[11px] uppercase tracking-[0.18em] text-[#6b6257]">
                        {availabilityLabel(provider.availability)}
                      </span>
                    </div>
                    {provider.description ? (
                      <p className="mt-2 text-[13px] text-[#6b6257]">{provider.description}</p>
                    ) : null}
                  </div>
                  <span
                    className={
                      provider.connected
                        ? "rounded-full border border-[#d7efe7] bg-[#ecfdf7] px-3 py-1 text-[11px] uppercase tracking-[0.18em] text-[#285b4a]"
                        : "rounded-full border border-[#efe7db] bg-white px-3 py-1 text-[11px] uppercase tracking-[0.18em] text-[#6b6257]"
                    }
                  >
                    {connectionLabel(provider)}
                  </span>
                </div>

                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <div className="rounded-xl border border-[#efe7db] bg-white px-3 py-3">
                    <p className="text-[11px] uppercase tracking-[0.18em] text-[#6b6257]">Last sync</p>
                    <p className="mt-1 text-[13px] text-[#1e1b16]">
                      {provider.last_sync_at ? formatDate(provider.last_sync_at) : "Not yet synced"}
                    </p>
                    {provider.last_sync_status ? (
                      <p className="mt-1 text-[11px] text-[#6b6257]">
                        Status: {String(provider.last_sync_status).replace(/_/g, " ")}
                      </p>
                    ) : null}
                  </div>
                  <div className="rounded-xl border border-[#efe7db] bg-white px-3 py-3">
                    <p className="text-[11px] uppercase tracking-[0.18em] text-[#6b6257]">Imported days</p>
                    <p className="mt-1 text-[13px] text-[#1e1b16]">{provider.metric_days_count || 0}</p>
                    {provider.latest_metric_date ? (
                      <p className="mt-1 text-[11px] text-[#6b6257]">
                        Latest: {formatDate(provider.latest_metric_date)}
                      </p>
                    ) : null}
                  </div>
                </div>

                {provider.note ? (
                  <p className="mt-4 text-[13px] leading-5 text-[#3c332b]">{provider.note}</p>
                ) : null}
                {provider.last_sync_error ? (
                  <p className="mt-3 text-[13px] text-[#8b3a2d]">{provider.last_sync_error}</p>
                ) : null}

                <div className="mt-4 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => void runAction(key, "connect")}
                    disabled={!canConnect || isBusy || isRefreshing}
                    className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-white disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {isBusy && canConnect ? "Opening..." : provider.connected ? "Connected" : "Connect"}
                  </button>
                  <button
                    type="button"
                    onClick={() => void runAction(key, "sync")}
                    disabled={!canSync || isBusy || isRefreshing}
                    className="rounded-full border border-[#e7e1d6] bg-white px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-[#3c332b] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {isBusy && canSync ? "Queueing..." : "Sync now"}
                  </button>
                  <button
                    type="button"
                    onClick={() => void runAction(key, "disconnect")}
                    disabled={!canDisconnect || isBusy || isRefreshing}
                    className="rounded-full border border-[#f0d4cd] bg-[#fff5f2] px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-[#8b3a2d] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {isBusy && canDisconnect ? "Disconnecting..." : "Disconnect"}
                  </button>
                </div>
              </div>
            );
          })() : null}
        </>
      )}
    </div>
  );
}
