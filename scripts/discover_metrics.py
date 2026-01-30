from google.cloud import monitoring_v3
import argparse

def list_metric_descriptors(project_id):
    client = monitoring_v3.MetricServiceClient()
    project_name = f"projects/{project_id}"
    
    descriptors = client.list_metric_descriptors(name=project_name)
    
    print(f"Metrics in project {project_id}:")
    for descriptor in descriptors:
        if any(x in descriptor.type.lower() for x in ["ctfe", "tesseract", "hammer", "latency", "throughput", "request"]):
            print(f"- {descriptor.type} ({descriptor.metric_kind})")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project_id", required=True)
    args = parser.parse_args()
    list_metric_descriptors(args.project_id)
