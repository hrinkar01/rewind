/**
 * Sample Node.js script with a fatal unhandled error for testing:
 *   rewind exec node tests/broken_node.js
 */

console.log("[Node.js] Starting order service worker...");
const session = { id: 1048, user: "Alice", balance: 500 };

console.log(`[Node.js] Loaded session for user ${session.user}`);

// Crash: Uncaught exception
if (session.balance > 100) {
  throw new Error("PaymentGatewayTimeoutError: Upstream bank API did not respond in 5000ms!");
}

console.log("[Node.js] Order processed successfully!");
