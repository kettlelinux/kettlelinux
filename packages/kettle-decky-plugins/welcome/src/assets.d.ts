// screenshots imported by the tour (rollup-plugin-import-assets: their URL, served by Decky)
declare module "*.jpg" {
  const url: string;
  export default url;
}
