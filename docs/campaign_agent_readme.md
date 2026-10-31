# Campaign episodes

Each folder under `episodes/` is one episode. Its name is an opaque identifier and its only file is `observations.jsonl.gz`, the observations as an agent receives them: one JSON row per reading, with the tag, the time of the measurement, the time at which it is available, the value, the unit and a quality flag.

Read an episode through the gateway, which returns what is available at a given time and nothing later: `from verum.api import Gateway`, then `Gateway(path_to_episode_folder).query(as_of_s)`. The result holds the observations, the list of assets and an empty inspection catalog.

`labels_train_validation.jsonl` has one row per labelled episode with its split (`train` or `validation`) and its faults. An episode without a row is a test episode: its labels are not in this folder. A healthy episode has an empty list of faults.

A fault has a type, a subtype, an asset, a severity in the units of the subtype, a class (`invisible`, `marginal`, `clear`, `latent` or `none`), an onset in seconds, a mode for a valve restriction and an activity (`active` or `latent`). A latent fault is on an asset that the lineup leaves idle and changes no observation.

Episodes last 3600 s. Nothing here says which scenario, stratum or tier an episode belongs to.
