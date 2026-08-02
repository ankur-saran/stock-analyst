{{/*
Common labels applied to every resource in this chart.
*/}}
{{- define "stock-analyst-data.labels" -}}
app.kubernetes.io/part-of: stock-analyst
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{/*
Node affinity pinning a pod to the data node (role=data).
*/}}
{{- define "stock-analyst-data.nodeAffinity" -}}
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
        - matchExpressions:
            - key: {{ .Values.global.nodeAffinity.key }}
              operator: In
              values:
                - {{ .Values.global.nodeAffinity.value }}
{{- end -}}
