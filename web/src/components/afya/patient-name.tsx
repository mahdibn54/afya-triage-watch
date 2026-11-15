import { fullName } from "@/lib/identity";

type Who = Parameters<typeof fullName>[0];

/** The case reference (the SYN- label), only when it adds something to the patient's name. */
export function caseRef(p: Who): string | null {
  return p.patient_name && p.patient_label ? p.patient_label : null;
}

/** Name first, case reference beside it in small type: "Lerato Ndlovu  SYN-n02-worst-headache". */
export function PatientName({ who }: { who: Who }) {
  const ref = caseRef(who);
  return (
    <>
      {fullName(who)}
      {ref && <span className="ml-2 font-mono text-xs font-normal text-muted-foreground">{ref}</span>}
    </>
  );
}
