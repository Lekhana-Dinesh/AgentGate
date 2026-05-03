export function cn(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "N/A";
  }
  return new Date(value).toLocaleString();
}

export function formatRisk(score: number): string {
  return `${Math.round(score)}/100`;
}

