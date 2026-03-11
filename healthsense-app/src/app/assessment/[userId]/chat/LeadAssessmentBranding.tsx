type LeadAssessmentBrandingProps = {
  className?: string;
  logoClassName?: string;
};

export default function LeadAssessmentBranding({
  className = "",
  logoClassName = "h-8 w-auto flex-none sm:h-9",
}: LeadAssessmentBrandingProps) {
  return (
    <span
      className={`inline-grid grid-cols-[auto_minmax(0,1fr)] items-center gap-3 leading-none ${className}`.trim()}
    >
      <img src="/healthsense-logo.svg" alt="HealthSense" className={logoClassName} />
      <span className="min-w-0 leading-tight">
        <span className="block">Find out your</span>
        <span className="block">HealthSense Score</span>
      </span>
    </span>
  );
}
