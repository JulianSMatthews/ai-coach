import type { PillarProgressGuidance } from "@/lib/api";
import GuidanceIcon from "@/components/GuidanceIcon";
import styles from "./PillarProgressPanel.module.css";

export default function ConceptGuidanceSections({ guidance }: { guidance: PillarProgressGuidance }) {
  return (
    <div className="space-y-4">
      {[
        { title: "One small step", icon: "step" as const, body: guidance.action, animation: styles.guidanceReveal },
        { title: "A moment to reflect", icon: "reflection" as const, body: guidance.reflection, animation: `${styles.guidanceReveal} ${styles.reflectionReveal}` },
      ].map((item) => (
        <div key={`${guidance.pillar_key}:${guidance.concept_key}:${item.title}`} className={`${item.animation} rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5 sm:p-6`}>
          <h3 className="flex items-center gap-2 text-base font-semibold text-[var(--text-primary)]">
            <GuidanceIcon kind={item.icon} />
            <span>{item.title}</span>
          </h3>
          <p className="mt-2 whitespace-pre-line text-base leading-7 text-[var(--text-secondary)]">{item.body}</p>
        </div>
      ))}
    </div>
  );
}
