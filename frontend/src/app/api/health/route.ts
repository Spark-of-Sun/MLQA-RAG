export const dynamic = "force-dynamic";

export function GET(): Response {
  return Response.json({ status: "ok" }); // liveness only, no detail (doc 15.7)
}
