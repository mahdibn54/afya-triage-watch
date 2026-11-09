/** Made-up (synthetic) patient identity for the screens. Older patients have no name: fall back to the label. */
type Who = { patient_name?: string | null; file_number?: string | null; patient_label?: string | null; visit_id: string };

/** "Amina Wanjiru" -> "A. W." */
export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => `${w[0].toUpperCase()}.`)
    .join(" ");
}

/** Board identity: initials when there is a name, else the label (or the visit id). */
export function shortName(p: Who): string {
  return p.patient_name ? initials(p.patient_name) : (p.patient_label ?? p.visit_id);
}

/** Panel, toasts and cards: the full name when there is one, else the label (or the visit id). */
export function fullName(p: Who): string {
  return p.patient_name ?? p.patient_label ?? p.visit_id;
}
