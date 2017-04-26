# Ambassador

Ambassador is an API Gateway for microservices built on [Envoy](https://lyft.github.io/envoy/). Key features in Ambassador include:

* Ability to flexibly map public URLs to services running inside a Kubernetes cluster
* Simple setup and configuration
* Integrated monitoring
* Authentication using TLS client certificates

# Quick Start

To get started with Ambassador, all you really need are some services that you can deploy in a Kubernetes cluster. You don't need to build anything.

Suppose we're building an application that comprises multiple services:

- We'll start with two services, but we'll need to easily add more later.
- We'll need to be able to see if our services are healthy, and to monitor their performance.
- We'll need to know that anyone talking to our service is allowed to do so.
- We'll need to use SSL everywhere.

We can do all of this with Ambassador. Let's start with getting a single service running.

## Deploy First Service

[deploy first service here -- crib from README]

## Deploy Ambassador

[deploy Ambassador with TLS -- crib from README]

### Enable Authentication

[add valid principals to Ambassador TLS auth -- need to write code here]

### Map First Service

[map first service through Ambassador -- crib from README]

### First Test!

[test without cert -- bzzzt]
[test with cert -- works]

Great, access and authentication are working!

## Statistics

We have a running and accessible service. What about stats? 

First, Ambassador has some stats built in that we can use for simple health checks:

```curl $AMBASSADORURL/ambassador/stats```

[crib more from README]

More than that, though, Ambassador automatically collects a number of stats internally, including latencies for calls to services and counters for successful and failing requests. It has built-in support to push these stats to [what exactly? DataDog and Prometheus?] -- all you need to do is configure it.

### DataDog

If you have a DataDog account, you can point Ambassador to DataDog with [instructions go here -- pretty sure this currently requires redeploying, so we need a better story here].

### Prometheus

[Prometheus story here]

### Test Statistics

Once you've done that, you can verify that Ambassador is writing stats with [some magic verification thing -- /ambassador/statsd maybe? who knows...], and then repeat your test of your service:

[test again]
[observe stats in statsd -- how?]

## Monitoring

[Do we want to talk about this?]

## Deploy Second Service

Now we can get our second service up and running. Note that it can reach the first service through Ambassador, but it needs to propagate the auth headers!

[sample code]
[deploy second service]
[map second service through Ambassador]
[test with & without certs]
[observe stats]

## Onward and Upward

Once you're up and running here, what else can you do?

### Upgrade Services

No problem. Just use `kubectl apply` to change the Docker image for one of your service; the new version will automagically be available.

### Add Services

Just deploy the new service, then map it through Ambassador. Done!

### What Services are Running?

Check Ambassador's `mappings` list to immediately know what's running behind the Ambassador:

```curl $AMBASSADORURL/ambassador/mappings```

