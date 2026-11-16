import { fullName } from "@/lib/identity";

type Who = Parameters<typeof fullName>[0];

/** The case reference (the SYN- label), only when it adds something to the patient's name. */
export function caseRef(p: Who): string | null {
  return p.patient_name && p.patient_label ? p.patient_label : null;
}

/** Name first, the file number beside it in small type: "Lerato Ndlovu  F-0217". The SYN case label stays out of the
 * nurse's screens (it is still in the audit view and the patient panel's details). */
export function PatientName({ who }: { who: Who }) {
  const ref = who.patient_name ? (who.file_number ?? null) : null;
  return (
    <>
      {fullName(who)}
      {ref && <span className="ml-2 font-mono text-xs font-normal text-muted-foreground">{ref}</span>}
    </>
  );
}
