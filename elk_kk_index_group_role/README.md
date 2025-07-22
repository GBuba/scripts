Один хелм в котором объеденены:

https://github.com/GBuba/scripts/tree/main/elk_auto_index

https://github.com/GBuba/scripts/blob/main/elk_keycloak_rolemappings.py

[https://git.moscow.alfaintra.net/projects/ALFAMESSAGING/repos/keycloak_groups_roles/browse](https://github.com/GBuba/scripts/blob/main/keycloak_groups_roles.py)


    Как пользоваться:
    git clone 
    cd elk_kk_index_group_role
    vi values.yaml (вносим нужные изменения)
    helm -n kibana install elk-kk-index-group-role . / helm -n kibana upgrade elk-kk-index-group-role .
    
    Запускать:
    kubectl create job --from=cronjob/elk-auto-index-py elk-auto-index-py-manual -n kibana && \
    kubectl create job --from=cronjob/keycloak-groups-roles keycloak-groups-roles-manual -n kibana && \
    sleep 5 && \
    kubectl create job --from=cronjob/keycloak-es-rolemapping keycloak-es-rolemapping-manual -n kibana
