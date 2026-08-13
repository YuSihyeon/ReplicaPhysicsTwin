#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "ReplicaOfficeVisualActor.generated.h"

class UProceduralMeshComponent;

/** Loads the derived office_0 visual mesh without giving it physics authority. */
UCLASS()
class REPLICAPHYSICSTWIN_API AReplicaOfficeVisualActor : public AActor
{
	GENERATED_BODY()

public:
	AReplicaOfficeVisualActor();

	virtual void BeginPlay() override;

	UPROPERTY(EditAnywhere, Category = "Replica Visual")
	FString SourceMeshPath = TEXT("../outputs/replica_cad/meshes/replica_cad_scene.rptmesh");

	bool IsMeshLoaded() const { return bMeshLoaded; }

private:
	UPROPERTY(VisibleAnywhere, Category = "Replica Visual")
	TObjectPtr<UProceduralMeshComponent> VisualMesh;

	bool bMeshLoaded = false;

	bool LoadDerivedMesh(const FString& AbsolutePath);
};
