/**
 * Invariant companion for dsh-sentiment-cockpit.
 */
const PACKAGE_NAME = "dsh-sentiment-cockpit";
const name = "sentiment-cockpit-invariant";
const inject = ["invariants"];
const install = () => {};
const apply = (ctx) => Promise.resolve(ctx.invariants.register(PACKAGE_NAME, install));
export { apply, inject, name };
