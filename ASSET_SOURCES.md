# Asset sources and licenses

This file separates visual references, generated source artwork, derived runtime
assets, and browser captures so that each file can be traced to its actual
origin. Ruacha selected and supplied the Mellowday-specific assets for this
repository and distributes the rights they hold in them under the repository's
[MIT License](LICENSE).

| Assets | Source record | Distribution record |
| --- | --- | --- |
| Five visual references under `docs/ui-concepts/themes/` | AI-generated with OpenAI Media Service API, `gpt-image` version `2.0`, on 2026-09-01 UTC. Each PNG contains an embedded C2PA manifest with that generator, model version, date, and `trainedAlgorithmicMedia` source type. Ruacha supplied and selected the images; they first entered the repository in commit `174b83f`. These are design references, not browser screenshots. | OpenAI's [Terms of Use](https://openai.com/policies/terms-of-use/) state that, as between the user and OpenAI and to the extent permitted by law, the user owns the Output. Ruacha distributes the selected output under the repository's MIT License. |
| Eight theme illustration source PNGs under `docs/ui-concepts/theme-assets/source/` | AI-generated with the same OpenAI Media Service API, `gpt-image` version `2.0`, and 2026-09-01 UTC C2PA record. Ruacha supplied and selected the images; they first entered the repository in commit `174b83f`. | Same OpenAI terms and repository MIT distribution record as the visual references above. |
| Theme WebP files under `docs/ui-concepts/theme-assets/runtime/`, `frontend/public/runtime/themes/`, and packaged static output | Derived and compressed from the corresponding AI-generated source PNGs. Candidate WebP files entered in commit `174b83f`; selected production derivatives entered in commit `6696d63`. The source PNGs retain the C2PA provenance even when a derived WebP does not. | MIT, for the rights held by Ruacha in the source output and project-specific derivatives. |
| Sky, Sakura, Mint, and Night motif SVGs | Simple project-specific vector paths created for Mellowday and committed by Ruacha in commit `174b83f`; no third-party source is recorded. Production copies entered in commit `6696d63`. | MIT |
| Prototype and validation captures under `docs/prototype/screenshots/` | Browser-rendered screenshots produced by the project's prototype and acceptance workflow and committed by Ruacha in commit `174b83f`. | MIT |
| Production baselines under `docs/visual-baselines/issue-48/` | Browser-rendered screenshots of the production React/Vite application, committed by Ruacha in commit `4789098`. | MIT |
| `frontend/public/runtime/status/ready.svg` and its packaged copy | Project-specific status vector created for Mellowday and committed by Ruacha in commit `8f3a9ce`. | MIT |
| Inter font files under `frontend/public/runtime/licenses/` and generated/package static output | Inter Project Authors, delivered through `@fontsource/inter` 5.3.0. The complete license text is preserved beside the runtime asset. | SIL Open Font License 1.1 |

The repository does not claim ownership of the Inter font. Its copyright and
license notice is available at
[`frontend/public/runtime/licenses/inter.txt`](frontend/public/runtime/licenses/inter.txt).
