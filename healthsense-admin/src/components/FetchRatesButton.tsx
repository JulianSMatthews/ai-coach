"use client";

import { useFormStatus } from "react-dom";

type FetchRatesButtonProps = {
  action: () => void | Promise<void>;
};

function FetchRatesSubmit() {
  const { pending } = useFormStatus();
  return (
    <div className="flex flex-col items-start gap-2">
      <button
        type="submit"
        disabled={pending}
        className="rounded-full border border-[#3f2e21] bg-[#3f2e21] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white disabled:cursor-not-allowed disabled:opacity-70"
      >
        {pending ? "Fetching..." : "Fetch provider rates"}
      </button>
      {pending ? <span className="text-xs text-[#8a8176]">Fetching rates from providers...</span> : null}
    </div>
  );
}

export default function FetchRatesButton({ action }: FetchRatesButtonProps) {
  return (
    <form action={action}>
      <FetchRatesSubmit />
    </form>
  );
}
