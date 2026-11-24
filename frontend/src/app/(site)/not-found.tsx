import { NotFoundContent } from "@/components/site/blocks";
import { auth0 } from "@/lib/auth0";

// notFound() inside the website (an unknown docs page or solution): the site layout already draws the chrome.
export default async function SiteNotFound() {
  return <NotFoundContent signedIn={Boolean(await auth0.getSession())} />;
}
