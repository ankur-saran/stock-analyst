{{- define "stock-analyst-app.labels" -}}
app.kubernetes.io/part-of: stock-analyst
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{/*
Node affinity pinning a pod to the app worker node (role=app).
*/}}
{{- define "stock-analyst-app.nodeAffinity" -}}
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
