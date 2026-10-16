import { redirect } from "next/navigation";

/** Old route name — kept so bookmarks and muscle memory still land. */
export default function ApprovalsRedirect() {
  redirect("/decisions");
}
