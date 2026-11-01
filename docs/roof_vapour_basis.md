# Roof, vapour and inspection basis

## Primary sources

| ID | Source | Use and boundary |
| --- | --- | --- |
| EPA-2026 | [AP-42 Chapter 7.1, June 2026](https://www.epa.gov/system/files/documents/2026-08/c7s1_2026.pdf), scope, sections 7.1.3.2/3, Tables 7.1-10/12, Example 4 | Normal maintained equipment coefficients and worked checks, not damaged-material calibration. |
| HMT-HFC | [HMT Aluminator HFC](https://www.hmttank.com/products/internal-floating-roofs/full-contact/aluminator-hfc-ifr/) | Roof family, not Verum connection ratings or seam classification. |
| HMT-SUPPORT | [HMT suspended roofs](https://www.hmttank.com/news/make-the-right-design-choice-to-engineer-safety-into-your-tanks/) | Nonpenetrating suspension is available; Verum explicitly specifies penetration groups. |
| HMT-LOAD | HMT ALLENTECH HC Analysis Report, 10 October 2024, page 6, public DCMR document 7036148 | Indexed manufacturer-authored PDF inspected. Its regulator landing URL was unavailable. Vent restriction can overload roof supports; ratings for that other roof are not transferred. |
| ASSENTECH-IFR | [Assentech IFR mechanisms](https://www.assentech.co.uk/products/internal-floating-roofs/) | Qualitative restraint damage and seal snagging, not a universal quantitative failure law. |
| OSHA-WORK | [OSHA 1910.146(h)(5), (i)(6)](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.146) | Maintained-condition/withdrawal principle, not a finding of plant or jurisdictional compliance. |
| ISO-PUMP | [ISO 10816-7 public scope](https://www.iso.org/standard/41726.html) | Pump vibration assessment scope only; no adopted head-loss-to-vibration transfer function. Full standard not used as a calibration source. |
| EPA-M21 | [EPA Method 21](https://www.epa.gov/sites/default/files/2017-08/documents/method_21.pdf), section 2.1 | VOC screening is not a direct mass-rate measurement or calibration of Verum's acoustic liquid-leak model. |

## Routine vapour

The separately hashed factor file records matched equipment coefficients and correlation limits. The routine module uses declared construction, actual seam dimensions and cumulative level decreases. Unmatched openings raise; honeycomb does not select a welded seam or automatic gauge well. Existing time conventions remain DESIGN selections. The result retains unknown uncertainty and incomplete facility qualification. No damage multiplier is fitted.

The unrestricted-well correlation requires known exposed area and adequate well height. Shorter or controlled configurations cannot use it. Withdrawal follows decreasing liquid level rather than gross discharge during simultaneous receipt. Reported quantities are model components, not VOC observations or inventory sinks. A full window still needs complete inventory, fluid and operating applicability review.

## Roof load and cascades

The existing M1 geometry/mass proxy supplies displacement and buoyancy. The bounded rigid restraint model has support demand `mg - buoyancy`; explicitly prescribed gas pressures can add `delta_p * deck_area`. Unknown gas pressure or strength is not filled in. This assessment does not solve vent flow, pressure, deformation or rupture. A manufacturer's allowable design load is not an ultimate failure load for Verum's different structure.

Native restrained-roof episodes bind full scenario/constraint inputs into their identity. They record actual coupled hydraulic and sensor responses, canonical roof truth and censored initial-condition metadata, with geometric corners retained for interpolation. They stay restricted. No secondary seal failure follows solely from liquid travel or normal roof landing.

Native restraint cases require an explicit `pressure_equalized_reference` gas-boundary declaration. This is a reference boundary, not a prediction that the fitted vents can maintain equal pressure. It is stored and bound into the episode identity. A blocked-vent cascade requires actual vent/leak-path geometry and gas-pressure dynamics, which these cases do not supply.

Quantitative cascades still require the load path, material/connection properties, vent configuration and a justified actual child-failure criterion. Qualitative mechanism evidence does not supply these. The archived 50 mm rule and proxy emissions require explicit research opt-in; no sourced universal threshold was substituted.

## Inspection

The default workflow checks recorded conditions throughout work, including start and completion. A failure cancels at its recorded occurrence, without disclosure at earlier approval. Unrecorded excursions, gas testing, access conditions and personnel procedures remain outside this reduced monitor. Unqualified roof/fitting, vibration and acoustic outcomes are missing/inconclusive; an availability flag is not a zero physical measurement.

Legacy numerical laws remain reproducible only through explicit research use. No generic vibration standard or VOC screening method is repurposed as a calibration of the selected baseline vibration, localisation error, or acoustic detection curve.

Valve pressure/travel measurements remain available independently of the legacy severity cutoffs. Default classification is inconclusive; unqualified normal/critical cutoffs are not read. A differential pressure alone does not define a universal valve-damage severity across flow rates and valve constructions.

Default level/calibration outputs likewise retain readings and stated uncertainty without asserting equipment acceptance through the legacy agreement rule. Default history contains recorded results only; no past maintenance is invented from uncalibrated normal-outcome probabilities. Explicit historical replay retains those old experimental rules and records.
