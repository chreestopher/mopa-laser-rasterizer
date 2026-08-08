sudo apt-get update 

#docker 
sudo apt-get install docker.io
sudo groupadd docker
sudo usermod -aG docker chree

#kind
sudo apt-get install kind

#k3s 
curl -sfL https://get.k3s.io | sh -
sudo systemctl start k3s
sudo systemctl enable k3s
sudo mkdir ~/.kube/config
sudo chmod 644 /etc/rancher/k3s/k3s.yaml
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config



sudo apt install build-essential libpotrace-dev libagg-dev pkg-config python3-dev