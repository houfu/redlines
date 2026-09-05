# Move worksheet: sla-1.0-to-2.0

Two clause lists, in document order, address and label only -- **no engine proposal anywhere on this page**. Read both columns fresh and note any clause that moved to a different position in the structure (not merely renumbered in place); write each one found as a `kind: move` row in `labels.yaml`, with `status: confirmed` or `corrected`. This is the one part of the labelling pass ADR-0034 requires to start from a blank sheet, never from the engine's own guess.

| source | test |
|---|---|
| `/section[1]/heading[1]`  -- Service Level Agreement Standard Terms | `/section[1]/heading[1]`  -- Service Level Agreement |
| `/section[1]/list_item[1]` 1 -- ## Uptime | `/section[1]/list_item[1]` 1 -- ## Uptime |
| `/section[1]/list_item[1]/list_item[1]` 1.1 -- Target Uptime. Provider will use commercially reasonable efforts to make the Cl… | `/section[1]/list_item[1]/list_item[1]` 1.1 -- Target Uptime. If there is a Target Uptime, Provider will use commercially reas… |
| `/section[1]/list_item[1]/list_item[2]` 1.2 -- Uptime Calculation. Provider and Customer agree to calculate availability of th… | `/section[1]/list_item[1]/list_item[2]` 1.2 -- Calculating Uptime. Provider and Customer agree to calculate availability of th… |
| `/section[1]/list_item[1]/list_item[3]` 1.3 -- Scheduling Downtime. If Provider does not notify Customer about Scheduled Downt… | `/section[1]/list_item[2]` 2 -- ## Response Time |
| `/section[1]/list_item[2]` 2 -- ## Remedies | `/section[1]/list_item[2]/list_item[1]` 2.1 -- Target Response Time. If there is a Target Response Time, Provider will use com… |
| `/section[1]/list_item[2]/list_item[1]` 2.1 -- Service Credit. If Cloud Service availability falls below the Target Uptime, Cu… | `/section[1]/list_item[2]/list_item[2]` 2.2 -- Calculating Response Time. Provider and Customer agree to calculate Provider’s … |
| `/section[1]/list_item[2]/list_item[2]` 2.2 -- Requesting A Service Credit. To receive a Service Credit, Customer must notify … | `/section[1]/list_item[3]` 3 -- ## Remedies |
| `/section[1]/list_item[2]/list_item[3]` 2.3 -- Service Credit Limitations. Service Credits may not be exchanged for, or conver… | `/section[1]/list_item[3]/list_item[1]` 3.1 -- Service Credit. If there is a Target Uptime and Cloud Service availability fall… |
| `/section[1]/list_item[2]/list_item[4]` 2.4 -- Termination. If the Cloud Service does not meet the Target Uptime for two (2) o… | `/section[1]/list_item[3]/list_item[2]` 3.2 -- Requesting A Service Credit. To receive a Service Credit, Customer must notify … |
| `/section[1]/list_item[2]/list_item[5]` 2.5 -- Exclusive Remedy. This SLA describes Customer’s exclusive remedy and Provider’s… | `/section[1]/list_item[3]/list_item[2]/list_item[1]` a -- For Uptime Credit, Customer must include information about when it was unable t… |
| `/section[1]/list_item[3]` 3 -- ## Definitions | `/section[1]/list_item[3]/list_item[2]/list_item[2]` b -- For Response Time Credit, Customer must include information about when and how … |
| `/section[1]/list_item[3]/paragraph[1]`  -- **“Available Minutes”** means the total number of minutes in a calendar month, … | `/section[1]/list_item[3]/list_item[3]` 3.3 -- Service Credit Limitations. Service Credits may not be exchanged for, or conver… |
| `/section[1]/list_item[3]/paragraph[2]`  -- **“Downtime Minutes”** means the total number of minutes in a calendar month wh… | `/section[1]/list_item[3]/list_item[4]` 3.4 -- Termination. If the Cloud Service does not meet the Target Uptime for two (2) o… |
| `/section[1]/list_item[3]/paragraph[3]`  -- **“Excluded Minutes”** means when the Cloud Service is not available because of… | `/section[1]/list_item[3]/list_item[5]` 3.5 -- Exclusive Remedy. This SLA describes Customer’s exclusive remedy and Provider’s… |
| `/section[1]/list_item[3]/paragraph[4]`  -- **“Scheduled Downtime”** means time periods that occur during the Maintenance W… | `/section[1]/list_item[4]` 4 -- ## Definitions |
|  | `/section[1]/list_item[4]/list_item[1]` 1 -- **"Available Minutes"** means the total number of minutes in a calendar month, … |
|  | `/section[1]/list_item[4]/list_item[2]` 2 -- **"Downtime Minutes"** means the total number of minutes in a calendar month wh… |
|  | `/section[1]/list_item[4]/list_item[3]` 3 -- **"Excluded Minutes"** means when the Cloud Service is not available because of… |
|  | `/section[1]/list_item[4]/list_item[4]` 4 -- **"Service Credit"** means the accrued Uptime Credit plus the accrued Response … |
|  | `/section[1]/list_item[4]/list_item[5]` 5 -- **"SLA"** means these SLA Standard Terms as incorporated into the applicable Or… |
|  | `/section[1]/list_item[4]/list_item[6]` 6 -- **"SLA Standard Terms"** means these Common Paper Service Level Agreement Stand… |
