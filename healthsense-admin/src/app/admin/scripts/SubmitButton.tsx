"use client";

import { useFormStatus } from "react-dom";

type SubmitButtonProps = {
  label: string;
  pendingLabel?: string;
  className?: string;
  pendingText?: string;
};

export default function SubmitButton({
  label,
  pendingLabel = "Starting…",
  className,
  pendingText = "Starting simulation… this can take a few seconds.",
}: SubmitButtonProps) {
  const { pending } = useFormStatus();

  return (
    <div className="flex flex-col gap-2">
      <button type="submit" className={className} disabled={pending}>
        {pending ? pendingLabel : label}
      </button>
      {pending ? (
        <p className="text-xs text-[#6b6257]" aria-live="polite">
          {pendingText}
        </p>
      ) : null}
    </div>
  );
}
