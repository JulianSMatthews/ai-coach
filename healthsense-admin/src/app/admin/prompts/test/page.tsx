import AdminNav from "@/components/AdminNav";
import TestPromptClient from "./TestPromptClient";

export default function TestPromptPage() {
  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-4xl space-y-6">
        <AdminNav title="Prompt tester" subtitle="Preview prompt assembly for a user and touchpoint." />
        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <TestPromptClient />
        </section>
      </div>
    </main>
  );
}
