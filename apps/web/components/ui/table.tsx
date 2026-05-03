import { ReactNode } from "react";

export function Table({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-3xl border border-slate-200 bg-white/90">
      <div className="overflow-x-auto">
        <table className="data-table min-w-full text-left text-sm">{children}</table>
      </div>
    </div>
  );
}

export function TableHead({ children }: { children: ReactNode }) {
  return <thead className="bg-slate-50">{children}</thead>;
}

export function TableBody({ children }: { children: ReactNode }) {
  return <tbody>{children}</tbody>;
}

export function Th({ children }: { children: ReactNode }) {
  return <th className="px-5 py-4 font-semibold">{children}</th>;
}

export function Td({ children }: { children: ReactNode }) {
  return <td className="border-t border-slate-100 px-5 py-4 align-top">{children}</td>;
}

