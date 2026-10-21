# Run Blackjack on Kubernetes

This guide uses the dashboard to learn the path from a container to Minikube
and then a managed cluster. Run commands from the repository root. You need
Docker, Minikube, and kubectl installed, with a running Docker daemon. The
image runs as a non-root user and uses headless OpenCV because the server has
no desktop display.

## 1. Build and run a container

```sh
docker build -t blackjack:dev .
docker volume create blackjack-data
docker run --rm --name blackjack -p 8000:8000 \
  -v blackjack-data:/var/lib/blackjack blackjack:dev
```

Open http://localhost:8000 and enter a card. In another terminal, inspect
`docker ps` and run `curl http://localhost:8000/health/ready`. Stop the
container with Ctrl+C. Run it again with the same volume and confirm your
card remains. The named volume stores SQLite outside the container.

## 2. Deploy to Minikube

```sh
minikube start --driver=docker
minikube image load blackjack:dev
kubectl apply -f k8s/blackjack.yaml
kubectl rollout status deployment/blackjack
kubectl get pods,pvc,service
kubectl port-forward service/blackjack 8000:80
```

Open http://localhost:8000. `Deployment` maintains one Pod; the PVC preserves
SQLite across Pod replacement; `Service` gives the Pod a stable cluster
address. In another terminal, try `kubectl logs deployment/blackjack`,
`kubectl describe pod -l app=blackjack`, and
`kubectl delete pod -l app=blackjack`. The Deployment creates a replacement;
refresh the page to check that the session persisted. Stop port-forward with
Ctrl+C.

## 3. Explore a LoadBalancer

```sh
kubectl apply -f k8s/loadbalancer.yaml
kubectl get service blackjack-public -w
```

On Minikube, `EXTERNAL-IP` may stay pending. In a second terminal, run
`minikube tunnel` and keep it open; inspect the Service again. Alternatively,
`minikube service blackjack-public --url` prints a reachable address for your
driver. The public Service selects the same Pod as the internal Service.
`kubectl get endpointslice -l kubernetes.io/service-name=blackjack-public`
shows its ready backend. A single Pod means traffic has only one destination;
this app is not ready for multiple replicas because WebSocket subscribers and
SQLite session state live inside one process. The LoadBalancer exercise teaches
network routing, not horizontal scaling.

If you use a non-local URL, set `BLACKJACK_ALLOWED_HOSTS` in
`k8s/blackjack.yaml` to include its hostname (without a port), then apply the
manifest again. The default allows localhost for port-forward. Use a browser
camera only on localhost or an HTTPS site, as browser camera access requires a
secure context. A Pod cannot directly open your laptop webcam with OpenCV.

## 4. Move to a managed cluster

Pick a provider and create a Kubernetes cluster and a container registry using
its console or CLI. Set kubectl's context to that cluster and check it with
`kubectl config current-context` and `kubectl get nodes` before applying
anything. Build and push an image tagged with your registry address and a
version, then change `image: blackjack:dev` in `k8s/blackjack.yaml` to that
address. Set `BLACKJACK_ALLOWED_HOSTS` to the intended public hostname, and
apply both manifests. Verify the PVC is Bound, the rollout succeeds, and the
LoadBalancer Service gets an address. Configure DNS for the hostname.

For real hosting, put HTTPS in front of the app using a provider load balancer
or ingress, and confirm WebSocket upgrades work through it. Do not publish the
current dashboard openly: it has no authentication, and every visitor can
modify the same session. Add authentication and access controls before making
it public. Keep one replica until you move session data to a shared store and
WebSocket notifications to a shared message channel. A single PVC does not
solve either problem. Check the provider's storage class, volume permissions,
backup options, and LoadBalancer charges before deploying.

To remove the Minikube exercise resources, run
`kubectl delete -f k8s/loadbalancer.yaml -f k8s/blackjack.yaml`. This deletes
the PVC and its stored session; run it only when you no longer need the data.
