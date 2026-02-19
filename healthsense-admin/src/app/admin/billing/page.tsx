import AdminNav from "@/components/AdminNav";
import {
  getBillingCatalog,
  syncBillingToStripe,
  upsertBillingPlan,
  upsertBillingPlanPrice,
} from "@/lib/api";
import { revalidatePath } from "next/cache";

export const dynamic = "force-dynamic";

function parseIntField(value: FormDataEntryValue | null, fallback = 0): number {
  const n = Number(String(value ?? "").trim());
  return Number.isFinite(n) ? Math.trunc(n) : fallback;
}

async function savePlanAction(formData: FormData) {
  "use server";
  const id = parseIntField(formData.get("plan_id"), 0);
  const code = String(formData.get("code") || "").trim();
  const name = String(formData.get("name") || "").trim();
  const description = String(formData.get("description") || "").trim();
  const isActive = Boolean(formData.get("is_active"));
  await upsertBillingPlan({
    id: id > 0 ? id : undefined,
    code,
    name,
    description: description || null,
    is_active: isActive,
  });
  revalidatePath("/admin/billing");
}

async function savePriceAction(formData: FormData) {
  "use server";
  const planId = parseIntField(formData.get("plan_id"), 0);
  if (!planId) {
    return;
  }
  const priceId = parseIntField(formData.get("price_id"), 0);
  const currency = String(formData.get("currency") || "").trim().toLowerCase();
  const amountMinor = parseIntField(formData.get("amount_minor"), 0);
  const currencyExponent = parseIntField(formData.get("currency_exponent"), 2);
  const interval = String(formData.get("interval") || "month").trim().toLowerCase();
  const intervalCount = parseIntField(formData.get("interval_count"), 1);
  const stripeProductId = String(formData.get("stripe_product_id") || "").trim();
  const stripePriceId = String(formData.get("stripe_price_id") || "").trim();
  const isActive = Boolean(formData.get("is_active"));
  const isDefault = Boolean(formData.get("is_default"));
  await upsertBillingPlanPrice(planId, {
    id: priceId > 0 ? priceId : undefined,
    currency,
    amount_minor: amountMinor,
    currency_exponent: currencyExponent,
    interval,
    interval_count: intervalCount,
    stripe_product_id: stripeProductId || null,
    stripe_price_id: stripePriceId || null,
    is_active: isActive,
    is_default: isDefault,
  });
  revalidatePath("/admin/billing");
}

async function syncStripeAction(formData: FormData) {
  "use server";
  const onlyActive = Boolean(formData.get("only_active"));
  const forceNew = Boolean(formData.get("force_new_prices"));
  await syncBillingToStripe({
    only_active: onlyActive,
    force_new_prices: forceNew,
  });
  revalidatePath("/admin/billing");
}

async function uploadCatalogJsonAction(formData: FormData) {
  "use server";
  const raw = String(formData.get("catalog_json") || "").trim();
  if (!raw) {
    return;
  }
  const parsed = JSON.parse(raw);
  const plans = Array.isArray(parsed) ? parsed : Array.isArray(parsed?.plans) ? parsed.plans : [];
  for (const item of plans) {
    const code = String(item?.code || "").trim();
    const name = String(item?.name || "").trim();
    if (!code || !name) {
      continue;
    }
    const savedPlan = await upsertBillingPlan({
      code,
      name,
      description: String(item?.description || "").trim() || null,
      is_active: Boolean(item?.is_active ?? true),
    });
    const planId = Number(savedPlan?.id || 0);
    if (!planId) {
      continue;
    }
    const prices = Array.isArray(item?.prices) ? item.prices : [];
    for (const price of prices) {
      const currency = String(price?.currency || "").trim().toLowerCase();
      const interval = String(price?.interval || "").trim().toLowerCase();
      if (!currency || !interval) {
        continue;
      }
      await upsertBillingPlanPrice(planId, {
        currency,
        amount_minor: Number(price?.amount_minor || 0),
        currency_exponent: Number(price?.currency_exponent ?? 2),
        interval,
        interval_count: Number(price?.interval_count ?? 1),
        is_active: Boolean(price?.is_active ?? true),
        is_default: Boolean(price?.is_default ?? false),
      });
    }
  }
  revalidatePath("/admin/billing");
}

export default async function BillingPage() {
  const data = await getBillingCatalog();
  const plans = data.plans || [];
  const stripe = data.stripe || {};

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-6xl space-y-6">
        <AdminNav title="Billing catalog" subtitle="Manage plans and sync Stripe Product/Price IDs." />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Stripe connection</p>
              <h2 className="mt-2 text-xl">Catalog sync</h2>
              <p className="mt-2 text-sm text-[#6b6257]">
                Stripe is {stripe.configured ? "configured" : "not configured"} · mode {stripe.mode || "unknown"} · API{" "}
                {stripe.api_base || "not set"}.
              </p>
            </div>
            <form action={syncStripeAction} className="flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-2 text-sm text-[#6b6257]">
                <input type="checkbox" name="only_active" defaultChecked />
                Only active plans/prices
              </label>
              <label className="flex items-center gap-2 text-sm text-[#6b6257]">
                <input type="checkbox" name="force_new_prices" />
                Force new Stripe Price IDs
              </label>
              <button
                type="submit"
                className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white"
              >
                Sync to Stripe
              </button>
            </form>
          </div>
        </section>

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div className="mb-4">
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Upload</p>
            <h2 className="mt-2 text-xl">Bulk catalog JSON</h2>
            <p className="mt-2 text-sm text-[#6b6257]">
              Paste JSON as an array of plans (or {"{ plans: [...] }"}) with optional nested prices, then save.
            </p>
          </div>
          <form action={uploadCatalogJsonAction} className="space-y-3">
            <textarea
              name="catalog_json"
              rows={8}
              placeholder='[{"code":"beta_monthly","name":"Beta Monthly","is_active":true,"prices":[{"currency":"gbp","amount_minor":9900,"interval":"month","interval_count":1,"is_default":true}]}]'
              className="w-full rounded-2xl border border-[#efe7db] px-4 py-3 text-sm font-mono"
            />
            <button
              type="submit"
              className="rounded-full border border-[#1e1b16] px-4 py-2 text-xs uppercase tracking-[0.2em]"
            >
              Upload catalog JSON
            </button>
          </form>
        </section>

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div className="mb-4">
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Create plan</p>
            <h2 className="mt-2 text-xl">Add billing plan</h2>
          </div>
          <form action={savePlanAction} className="grid gap-3 md:grid-cols-5">
            <input type="hidden" name="plan_id" value="" />
            <input
              name="code"
              placeholder="beta_monthly"
              className="rounded-xl border border-[#efe7db] px-3 py-2 text-sm md:col-span-1"
              required
            />
            <input
              name="name"
              placeholder="HealthSense Monthly"
              className="rounded-xl border border-[#efe7db] px-3 py-2 text-sm md:col-span-2"
              required
            />
            <input
              name="description"
              placeholder="Monthly coaching subscription"
              className="rounded-xl border border-[#efe7db] px-3 py-2 text-sm md:col-span-2"
            />
            <label className="flex items-center gap-2 text-sm text-[#6b6257] md:col-span-4">
              <input type="checkbox" name="is_active" defaultChecked />
              Active
            </label>
            <button
              type="submit"
              className="rounded-full border border-[#1e1b16] px-4 py-2 text-xs uppercase tracking-[0.2em] md:justify-self-end"
            >
              Save plan
            </button>
          </form>
        </section>

        <section className="space-y-4">
          {plans.map((plan) => (
            <div key={plan.id} className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
              <form action={savePlanAction} className="grid gap-3 md:grid-cols-6">
                <input type="hidden" name="plan_id" value={plan.id} />
                <div className="md:col-span-1">
                  <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Code</label>
                  <input
                    name="code"
                    defaultValue={plan.code || ""}
                    className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                    required
                  />
                </div>
                <div className="md:col-span-2">
                  <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Name</label>
                  <input
                    name="name"
                    defaultValue={plan.name || ""}
                    className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                    required
                  />
                </div>
                <div className="md:col-span-2">
                  <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Description</label>
                  <input
                    name="description"
                    defaultValue={plan.description || ""}
                    className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                  />
                </div>
                <div className="md:col-span-1 flex items-end justify-end">
                  <button
                    type="submit"
                    className="rounded-full border border-[#1e1b16] px-4 py-2 text-xs uppercase tracking-[0.2em]"
                  >
                    Save plan
                  </button>
                </div>
                <label className="md:col-span-6 flex items-center gap-2 text-sm text-[#6b6257]">
                  <input type="checkbox" name="is_active" defaultChecked={Boolean(plan.is_active)} />
                  Active
                </label>
              </form>

              <div className="mt-6 space-y-3">
                <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Prices</p>
                {(plan.prices || []).map((price) => (
                  <form key={price.id} action={savePriceAction} className="grid gap-3 rounded-2xl border border-[#efe7db] p-4 md:grid-cols-12">
                    <input type="hidden" name="plan_id" value={plan.id} />
                    <input type="hidden" name="price_id" value={price.id} />
                    <div className="md:col-span-1">
                      <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">CCY</label>
                      <input
                        name="currency"
                        defaultValue={price.currency || "gbp"}
                        className="mt-2 w-full rounded-xl border border-[#efe7db] px-2 py-2 text-sm"
                        maxLength={3}
                      />
                    </div>
                    <div className="md:col-span-2">
                      <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Amount minor</label>
                      <input
                        name="amount_minor"
                        type="number"
                        defaultValue={price.amount_minor ?? 0}
                        className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                      />
                    </div>
                    <div className="md:col-span-2">
                      <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Interval</label>
                      <select
                        name="interval"
                        defaultValue={price.interval || "month"}
                        className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                      >
                        <option value="month">month</option>
                        <option value="year">year</option>
                        <option value="one_time">one_time</option>
                      </select>
                    </div>
                    <div className="md:col-span-1">
                      <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Count</label>
                      <input
                        name="interval_count"
                        type="number"
                        min={1}
                        defaultValue={price.interval_count ?? 1}
                        className="mt-2 w-full rounded-xl border border-[#efe7db] px-2 py-2 text-sm"
                      />
                    </div>
                    <div className="md:col-span-1">
                      <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Exp</label>
                      <input
                        name="currency_exponent"
                        type="number"
                        min={0}
                        max={4}
                        defaultValue={price.currency_exponent ?? 2}
                        className="mt-2 w-full rounded-xl border border-[#efe7db] px-2 py-2 text-sm"
                      />
                    </div>
                    <div className="md:col-span-2">
                      <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Stripe product</label>
                      <input
                        name="stripe_product_id"
                        defaultValue={price.stripe_product_id || ""}
                        className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                      />
                    </div>
                    <div className="md:col-span-2">
                      <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Stripe price</label>
                      <input
                        name="stripe_price_id"
                        defaultValue={price.stripe_price_id || ""}
                        className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                      />
                    </div>
                    <div className="md:col-span-8 flex flex-wrap items-center gap-4">
                      <label className="flex items-center gap-2 text-sm text-[#6b6257]">
                        <input type="checkbox" name="is_active" defaultChecked={Boolean(price.is_active)} />
                        Active
                      </label>
                      <label className="flex items-center gap-2 text-sm text-[#6b6257]">
                        <input type="checkbox" name="is_default" defaultChecked={Boolean(price.is_default)} />
                        Default
                      </label>
                    </div>
                    <div className="md:col-span-4 flex items-center justify-end">
                      <button
                        type="submit"
                        className="rounded-full border border-[#1e1b16] px-4 py-2 text-xs uppercase tracking-[0.2em]"
                      >
                        Save price
                      </button>
                    </div>
                  </form>
                ))}

                <form action={savePriceAction} className="grid gap-3 rounded-2xl border border-dashed border-[#efe7db] p-4 md:grid-cols-12">
                  <input type="hidden" name="plan_id" value={plan.id} />
                  <input type="hidden" name="price_id" value="" />
                  <div className="md:col-span-1">
                    <input
                      name="currency"
                      defaultValue="gbp"
                      className="w-full rounded-xl border border-[#efe7db] px-2 py-2 text-sm"
                      maxLength={3}
                      placeholder="ccy"
                    />
                  </div>
                  <div className="md:col-span-2">
                    <input
                      name="amount_minor"
                      type="number"
                      defaultValue={0}
                      className="w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                      placeholder="amount_minor"
                    />
                  </div>
                  <div className="md:col-span-2">
                    <select
                      name="interval"
                      defaultValue="month"
                      className="w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                    >
                      <option value="month">month</option>
                      <option value="year">year</option>
                      <option value="one_time">one_time</option>
                    </select>
                  </div>
                  <div className="md:col-span-1">
                    <input
                      name="interval_count"
                      type="number"
                      min={1}
                      defaultValue={1}
                      className="w-full rounded-xl border border-[#efe7db] px-2 py-2 text-sm"
                      placeholder="count"
                    />
                  </div>
                  <div className="md:col-span-1">
                    <input
                      name="currency_exponent"
                      type="number"
                      min={0}
                      max={4}
                      defaultValue={2}
                      className="w-full rounded-xl border border-[#efe7db] px-2 py-2 text-sm"
                      placeholder="exp"
                    />
                  </div>
                  <div className="md:col-span-5 flex flex-wrap items-center gap-4">
                    <label className="flex items-center gap-2 text-sm text-[#6b6257]">
                      <input type="checkbox" name="is_active" defaultChecked />
                      Active
                    </label>
                    <label className="flex items-center gap-2 text-sm text-[#6b6257]">
                      <input type="checkbox" name="is_default" />
                      Default
                    </label>
                    <button
                      type="submit"
                      className="rounded-full border border-[#1e1b16] px-4 py-2 text-xs uppercase tracking-[0.2em]"
                    >
                      Add price
                    </button>
                  </div>
                </form>
              </div>
            </div>
          ))}
          {!plans.length ? (
            <div className="rounded-2xl border border-dashed border-[#e7e1d6] bg-white p-6 text-sm text-[#6b6257]">
              No plans yet. Create a plan above to start your billing catalog.
            </div>
          ) : null}
        </section>
      </div>
    </main>
  );
}
