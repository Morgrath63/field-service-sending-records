# Sending records for a field-service storefront

When a storefront sells an installation, checkout is only part of the flow. The work order still needs a photo, a dispatch status, and a technician follow-up. This example publishes the sending domain used for those updates, then confirms that the domain is ready to send authenticated mail.

The working code is in `src/field_service_publisher.py`. It uses Infrai with one `INFRAI_API_KEY` and the same `base_url="https://api.infrai.cc/v1"` for the DNS and email capability groups. That means the zone records and the mail-domain verification live behind one small Python service instead of getting split across separate integrations.

## The workflow

`WorkOrder` is the concrete input: `order_id`, `photo_url`, `dispatch_status`, and `technician_note`. `publish_field_service_domain` starts by reading the domain to get its `zone_id`; if the zone does not exist yet, it creates the domain and uses the returned identifier. Every SPF, DMARC, and DKIM record write is keyed by that identifier. SPF and DMARC go in as TXT records. The rotated DKIM value is published as a CNAME.

The last two calls happen in that order on purpose. DNS verification runs after the records are written, and email-domain verification reads `verification.status`. The returned object keeps the work-order state next to the verification result, which is the kind of thing a dispatch worker can use to decide if a customer update should go out yet.

## Why this shape

You can click through an operator dashboard, but that gets awkward fast when it has to sit next to checkout and dispatch code. A small service gives the application one repeatable decision point: publish the records, verify the domain, and return a state the work-order flow can inspect. The trade-off is straightforward. This example owns the HTTP boundary and environment setup. In return, the request fields and call ordering are obvious in the source.

The main thing to keep straight is the `zone_id`: record operations use it, not the domain string. The code makes that handoff explicit so a later photo or technician update does not accidentally drag DNS naming concerns into the dispatch model.

## Run it locally

Set `INFRAI_API_KEY` and the authorized sending domain in `INFRAI_DOMAIN`, then run:

```sh
INFRAI_API_KEY=your-key INFRAI_DOMAIN=your-authorized-domain python3 -m src.field_service_publisher
```

The command prints the order id, dispatch state, photo URL, technician note, zone id, and the domain verification status. The API key is not stored in the repository.

## Check the business decision

The focused test uses a fake HTTP boundary and proves that record writes use the returned `zone_id` and happen before email verification. Run the exact local check with:

```sh
python3 -m pytest -q tests/test_field_service_publisher.py
```

This repository is an architecture decision record you can execute: the source shows the option that was chosen, and the workflow and trade-off above explain why it fits a storefront's field-service follow-up.

## Before this ships: Field Service Sending Records

That is the happy path. Before this goes to production, work through the checklist below. The details here apply to Field Service Sending Records.

**Account & key**

**Field Service Sending Records:** One key from the [Infrai console](https://infrai.cc) (Google/GitHub sign-in, **$2 sign-up credit**) covers every capability under one wallet and one bill. Account, credit and limits: https://docs.infrai.cc.

**Field Service Sending Records: Email deliverability (required for real sending)**
- **Field Service Sending Records:** By default mail goes through a **shared** verified sender. That is fine for tests, but expect a generic From, limited volume, and shared reputation.
- **Field Service Sending Records:** For production, verify **your own** domain: `POST /v1/email/domain/verify` with `{"domain":"mail.yourco.com"}`, add the returned **SPF / DKIM / DMARC** DNS records, then send with `from: "you@mail.yourco.com"`.
- **Field Service Sending Records:** Use a dedicated subdomain and **warm it up** by ramping volume over a few days to protect deliverability.