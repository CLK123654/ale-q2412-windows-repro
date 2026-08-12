{{- define "callback-keyring.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "callback-keyring.validate" -}}
{{- $seen := dict -}}
{{- $activeFound := false -}}
{{- range $id := .Values.acceptedKeys -}}
  {{- if hasKey $seen $id -}}
    {{- fail (printf "duplicate accepted key %s" $id) -}}
  {{- end -}}
  {{- $_ := set $seen $id true -}}
  {{- if eq $id $.Values.activeKey -}}
    {{- $activeFound = true -}}
  {{- end -}}
  {{- if not (hasKey $.Values.secretRefs $id) -}}
    {{- fail (printf "accepted key %s missing from secretRefs" $id) -}}
  {{- end -}}
{{- end -}}
{{- if not $activeFound -}}
  {{- fail (printf "active key %s must appear in acceptedKeys" .Values.activeKey) -}}
{{- end -}}
{{- end -}}
