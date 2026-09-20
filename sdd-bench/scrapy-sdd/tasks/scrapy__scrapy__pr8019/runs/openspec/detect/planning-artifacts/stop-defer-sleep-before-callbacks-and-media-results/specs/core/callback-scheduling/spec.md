## Purpose

Define when Scrapy may invoke spider callbacks and deliver media-pipeline download results, so that such work is never run before the event loop has had a chance to process pending I/O, and is never delayed by a fixed amount of time.

## ADDED Requirements

### Requirement: Pending I/O is processed before callbacks

Before invoking a spider callback or errback for a downloaded response, the engine SHALL give the event loop an opportunity to process pending reader and writer callbacks, so that work scheduled by previously completed I/O is not starved by the callback.

#### Scenario: Callback runs after pending I/O callbacks

- **WHEN** a response is scheduled for a spider callback while other I/O callbacks are pending
- **THEN** those pending I/O callbacks have run before the spider callback is invoked

### Requirement: No fixed delay before callbacks or media results

Scrapy SHALL NOT insert a fixed delay (previously 100 ms) before invoking a spider callback or before making a media-pipeline download result available. Yielding to the event loop SHALL NOT be expressed as a wall-clock sleep.

#### Scenario: Back-to-back callbacks are not delayed

- **WHEN** a crawl processes multiple responses whose callbacks perform no asynchronous work
- **THEN** the elapsed time does not grow by a fixed delay per response

#### Scenario: Single media download is not delayed

- **WHEN** a media request is downloaded and cached for one item
- **THEN** the result is returned as soon as the download and pending I/O processing complete, with no additional fixed delay

### Requirement: Waiting media requests receive the cached result promptly

When several media requests share a fingerprint and one of them completes, all requests waiting on that fingerprint SHALL be resolved with the cached result without an additional fixed delay, and later requests for the same fingerprint SHALL receive the cached result.

#### Scenario: Waiters resolved on completion

- **WHEN** two media requests share a fingerprint and the download of the first completes
- **THEN** both requests produce the same result and neither waits on a fixed delay

#### Scenario: Cached failures keep their errback behavior

- **WHEN** a cached media result is a failure and the request defines an errback
- **THEN** the errback is called with that failure
