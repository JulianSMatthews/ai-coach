"use client";

type ConfirmDeleteButtonProps = {
  formId: string;
  templateId: number;
};

export default function ConfirmDeleteButton({ formId, templateId }: ConfirmDeleteButtonProps) {
  return (
    <button
      type="submit"
      name="template_delete_id"
      value={templateId}
      form={formId}
      onClick={(event) => {
        if (!confirm("Delete this template? This will remove it in Twilio if the SID exists.")) {
          event.preventDefault();
        }
      }}
      className="rounded-full border border-[#b45309] bg-[#b45309] px-4 py-2 text-xs uppercase tracking-[0.2em] text-white"
    >
      Delete
    </button>
  );
}
