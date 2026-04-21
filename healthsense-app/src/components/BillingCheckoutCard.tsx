"use client";

import { useEffect, useMemo, useState } from "react";
import type { BillingPlanOption } from "@/lib/api";

type BillingCheckoutCardProps = {
  userId: string;
  billingState?: string | null;
  billingFlag?: string | null;
  plans?: BillingPlanOption[];
  defaultPriceId?: number | null;
};

function normalizeBillingState(value?: string | null) {
  const state = String(value || "").trim().toLowerCase();
  if (["active", "trialing", "beta"].includes(state)) return "active";
  if (["past_due", "unpaid", "canceled", "cancelled", "incomplete", "incomplete_expired"].includes(state)) return "inactive";
  return "unknown";
}

export default function BillingCheckoutCard({
  userId,
  billingState,
  billingFlag,
  plans = [],
  defaultPriceId = null,
}: BillingCheckoutCardProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [readOnlyPreview, setReadOnlyPreview] = useState(false);
  const [selectedPriceId, setSelectedPriceId] = useState<string>("");
  const [nativeIosApp, setNativeIosApp] = useState(false);
  const state = normalizeBillingState(billingState);
  const billingTag = String(billingFlag || "").trim().toLowerCase();
  const formatPrice = (amountMinor?: number, exponent?: number, currency?: string) => {
    const amt = Number(amountMinor ?? 0);
    const exp = Number(exponent ?? 2);
    const ccy = String(currency || "gbp").toUpperCase();
    if (!Number.isFinite(amt) || !Number.isFinite(exp)) return `${amt} ${ccy}`;
    const value = amt / Math.pow(10, exp);
    try {
      return new Intl.NumberFormat("en-GB", {
        style: "currency",
        currency: ccy,
        maximumFractionDigits: exp,
        minimumFractionDigits: exp,
      }).format(value);
    } catch {
      return `${value.toFixed(Math.max(0, exp))} ${ccy}`;
    }
  };

  const options = useMemo(() => {
    const list: Array<{ value: string; label: string }> = [];
    for (const plan of plans) {
      const planName = String(plan?.name || plan?.code || "Plan").trim();
      for (const price of plan?.prices || []) {
        const priceId = Number(price?.id || 0);
        if (!Number.isInteger(priceId) || priceId <= 0) continue;
        const interval = String(price?.interval || "month").toLowerCase();
        const intervalCount = Math.max(1, Number(price?.interval_count || 1));
        const suffix =
          interval === "one_time"
            ? "one-off"
            : intervalCount > 1
            ? `every ${intervalCount} ${interval}s`
            : `per ${interval}`;
        list.push({
          value: String(priceId),
          label: `${planName} - ${formatPrice(price?.amount_minor, price?.currency_exponent, price?.currency)} (${suffix})`,
        });
      }
    }
    return list;
  }, [plans]);

  useEffect(() => {
    if (typeof navigator !== "undefined") {
      setNativeIosApp(/\bHealthSenseIOS\//i.test(navigator.userAgent));
    }
  }, []);

  useEffect(() => {
    if (!options.length) {
      setSelectedPriceId("");
      return;
    }
    const preferred = defaultPriceId ? String(defaultPriceId) : "";
    if (preferred && options.some((opt) => opt.value === preferred)) {
      setSelectedPriceId(preferred);
      return;
    }
    setSelectedPriceId((prev) => (prev && options.some((opt) => opt.value === prev) ? prev : options[0].value));
  }, [defaultPriceId, options]);

  const statusLabel = useMemo(() => {
    if (billingTag === "success") return "Payment confirmed";
    if (billingTag === "cancel") return "Checkout cancelled";
    if (state === "active") return "Subscription active";
    if (state === "inactive") return "Subscription requires attention";
    return "Subscription not configured";
  }, [billingTag, state]);

  const statusColor = useMemo(() => {
    if (billingTag === "success") return "#027a48";
    if (billingTag === "cancel") return "#b54708";
    if (state === "active") return "#027a48";
    if (state === "inactive") return "#b42318";
    return "#6b6257";
  }, [billingTag, state]);

  const subscribe = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/billing/checkout-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userId,
          price_id: selectedPriceId ? Number(selectedPriceId) : undefined,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const rawError = String(data?.error || `Checkout request failed (${res.status})`);
        const code = String(data?.code || "").trim().toLowerCase();
        const isAdminPreview = code === "admin_preview_read_only" || rawError.toLowerCase().includes("admin preview");
        if (isAdminPreview) {
          setReadOnlyPreview(true);
          throw new Error("Checkout is unavailable in admin preview. Open the user app session to set up subscription.");
        }
        throw new Error(rawError);
      }
      const checkoutUrl = String(data?.checkout_url || "").trim();
      if (!checkoutUrl) {
        throw new Error("Stripe checkout URL missing from response.");
      }
      window.location.href = checkoutUrl;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setLoading(false);
    }
  };

  return (
    <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
      <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Subscription</p>
      <p className="mt-2 text-sm" style={{ color: statusColor }}>
        {statusLabel}
      </p>
      {billingTag === "success" ? (
        <p className="mt-2 text-xs text-[#6b6257]">Your billing has been updated. Access changes may take a few seconds.</p>
      ) : null}
      {billingTag === "cancel" ? (
        <p className="mt-2 text-xs text-[#6b6257]">No payment was taken. You can start checkout again when ready.</p>
      ) : null}
      {state !== "active" ? (
        <>
          {nativeIosApp ? (
            <div className="mt-3 rounded-2xl border border-[#efe7db] bg-[#fffaf3] px-4 py-3">
              <p className="text-sm text-[#6b6257]">
                Subscription setup for the HealthSense coaching service is managed directly with HealthSense staff. No
                payment is taken inside this iOS app.
              </p>
              <a className="mt-2 inline-block text-sm text-[var(--accent)] underline" href="/support">
                Contact support
              </a>
            </div>
          ) : (
            <>
              <label className="mt-3 block text-xs uppercase tracking-[0.2em] text-[#6b6257]">Choose plan</label>
              <select
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                value={selectedPriceId}
                onChange={(e) => setSelectedPriceId(e.target.value)}
                disabled={!options.length || loading || readOnlyPreview}
              >
                {!options.length ? <option value="">No active plans available</option> : null}
                {options.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={subscribe}
                disabled={loading || !selectedPriceId || readOnlyPreview}
                className="mt-3 rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-white disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading ? "Opening checkout..." : "Set up subscription"}
              </button>
            </>
          )}
          {readOnlyPreview ? (
            <p className="mt-2 text-xs text-[#6b6257]">
              Admin preview is read-only. Open the user app session to complete subscription setup.
            </p>
          ) : null}
        </>
      ) : null}
      {error ? <p className="mt-2 text-xs text-[#b42318]">{error}</p> : null}
    </div>
  );
}
