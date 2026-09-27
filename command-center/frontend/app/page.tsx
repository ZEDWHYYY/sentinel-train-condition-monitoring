import { redirect } from "next/navigation";

/** Upload is the primary workflow. */
export default function Home() {
  redirect("/analyze");
}
