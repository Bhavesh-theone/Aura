/**
 * Deal intake — upload documents, let Aura extract the deal, review with
 * confidence + citations, confirm to create it. Other features import ONLY
 * from here.
 */
export { DealIntakeWizard } from "./components/DealIntakeWizard";
export { IntakeDraftsList } from "./components/IntakeDraftsList";

/** Where the wizard lives; `/deals/new?intake=<id>` resumes a draft. */
const intakeHref = (intakeId?: number) => (intakeId ? `/deals/new?intake=${intakeId}` : "/deals/new");

/** Open the intake wizard (a fresh draft, or resume one). Pass the app router. */
export function openIntake(router: { push: (href: string) => void }, intakeId?: number) {
  router.push(intakeHref(intakeId));
}
