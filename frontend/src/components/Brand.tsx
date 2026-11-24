export function BrandMark() {
  return (
    <div className="flex items-center gap-2 text-primary">
      <span className="flex h-6 w-6 items-center justify-center rounded-md bg-primary text-xs font-bold text-white">
        t
      </span>
      <span className="font-sans text-[17px] font-semibold tracking-tight">Toolkit</span>
    </div>
  );
}

export function DataIllustration() {
  return (
    <div className="relative mx-auto h-[310px] w-full max-w-[390px]" aria-hidden="true">
      <div className="absolute left-[24%] top-[13%] h-[190px] w-[235px] rotate-[-8deg] rounded-lg border border-border bg-white/80 p-4 shadow-sm">
        <div className="grid h-full grid-cols-4 grid-rows-5 overflow-hidden rounded border border-border/70">
          {Array.from({ length: 20 }, (_, index) => (
            <div
              key={index}
              className={`border-b border-r border-border/70 ${
                index === 0 || index === 6 || index === 13 ? "bg-sage" : "bg-white/80"
              }`}
            />
          ))}
        </div>
      </div>
      <div className="absolute left-[19%] top-[28%] h-[132px] w-[40px] rotate-[18deg] rounded-full bg-[#E4ECE4]" />
      <span className="absolute right-[13%] top-[13%] h-3 w-3 rounded-full bg-gold" />
      <span className="absolute right-[8%] top-[34%] text-2xl text-gold">✦</span>
      <span className="absolute left-[16%] top-[61%] text-lg text-gold">✦</span>
      <div className="absolute bottom-[13%] right-[8%] flex h-[88px] w-[174px] items-center justify-center gap-3 rounded-[28px] rounded-bl-md bg-primary text-white shadow-sm">
        <span className="h-2.5 w-2.5 rounded-full bg-white" />
        <span className="h-2.5 w-2.5 rounded-full bg-white" />
        <span className="h-2.5 w-2.5 rounded-full bg-white" />
        <span className="absolute -bottom-4 left-7 h-8 w-8 -rotate-12 rounded-bl-full bg-primary" />
      </div>
      <p className="absolute bottom-0 w-full text-center text-[11px] text-muted">
        Good questions. Clear answers. Your next step.
      </p>
    </div>
  );
}
