// See package.json: never loaded unless experimental.optimizeCss is turned on in next.config.ts.
module.exports = function Critters() {
  throw new Error("critters is not installed: experimental.optimizeCss is not supported in this build");
};
