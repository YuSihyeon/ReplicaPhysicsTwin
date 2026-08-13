#include "Bridge/MuJoCoBridgeDemoGameMode.h"

#include "Bridge/MuJoCoBridgeDemoActor.h"
#include "Bridge/MuJoCoBridgeDemoPlayerController.h"
#include "Bridge/ReplicaOfficeVisualActor.h"
#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "Components/DirectionalLightComponent.h"
#include "Components/PointLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/DirectionalLight.h"
#include "Engine/PointLight.h"
#include "Engine/StaticMeshActor.h"
#include "GameFramework/PlayerController.h"
#include "Kismet/GameplayStatics.h"
#include "DrawDebugHelpers.h"
#include "Dom/JsonObject.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/UObjectGlobals.h"

namespace
{
struct FInteractionBodyPresentation
{
	FString ObjectId;
	int32 SourceObjectId = INDEX_NONE;
	FVector InitialLocationCm = FVector::ZeroVector;
	FVector FullSizeCm = FVector::ZeroVector;
	FLinearColor Color = FLinearColor::White;
	FString LocalVisualMeshPath;
	bool bDeformable = false;
	int32 ClothGridCols = 0;
	int32 ClothGridRows = 0;
	FVector ClothLocalBoundsMinCm = FVector::ZeroVector;
	FVector ClothLocalBoundsMaxCm = FVector::ZeroVector;
};

struct FReplicaPresentationBounds
{
	bool bValid = false;
	bool bRoomBoundsValid = false;
	FVector SceneBoundsMinCm = FVector::ZeroVector;
	FVector SceneBoundsMaxCm = FVector::ZeroVector;
	FVector FocusCm = FVector::ZeroVector;
	FVector RoomBoundsMinCm = FVector::ZeroVector;
	FVector RoomBoundsMaxCm = FVector::ZeroVector;
	float RecommendedDistanceCm = 0.0f;
};

void ComputeReplicaCameraFrame(
	const TArray<FInteractionBodyPresentation>& Bodies,
	const FReplicaPresentationBounds& PresentationBounds,
	FVector& OutLocation,
	FVector& OutFocus)
{
	FVector Minimum = FVector::ZeroVector;
	FVector Maximum = FVector::ZeroVector;
	FVector DynamicMinimum = FVector::ZeroVector;
	FVector DynamicMaximum = FVector::ZeroVector;
	bool bDynamicBoundsValid = false;
	for (const FInteractionBodyPresentation& Body : Bodies)
	{
		const FVector Extent = Body.FullSizeCm * 0.5f;
		if (!bDynamicBoundsValid)
		{
			DynamicMinimum = Body.InitialLocationCm - Extent;
			DynamicMaximum = Body.InitialLocationCm + Extent;
			bDynamicBoundsValid = true;
		}
		else
		{
			DynamicMinimum = DynamicMinimum.ComponentMin(Body.InitialLocationCm - Extent);
			DynamicMaximum = DynamicMaximum.ComponentMax(Body.InitialLocationCm + Extent);
		}
	}
	if (PresentationBounds.bValid)
	{
		// The visual room contains many static objects that are not in the
		// selected-body list.  Keep the exported bounds for safety limits, but
		// do not use the full-room AABB as the photographic target: that creates
		// a distant shot where the bike and garments are unreadable.
		Minimum = PresentationBounds.SceneBoundsMinCm;
		Maximum = PresentationBounds.SceneBoundsMaxCm;
		OutFocus = bDynamicBoundsValid
			? (DynamicMinimum + DynamicMaximum) * 0.5f + FVector(0.0f, 0.0f, -15.0f)
			: PresentationBounds.FocusCm;
	}
	else if (Bodies.Num() > 0)
	{
		Minimum = DynamicMinimum;
		Maximum = DynamicMaximum;
		OutFocus = (DynamicMinimum + DynamicMaximum) * 0.5f;
	}
	else
	{
		OutLocation = FVector(-100.0f, 130.0f, 300.0f);
		OutFocus = FVector::ZeroVector;
		return;
	}

	const FVector Span = Maximum - Minimum;
	const float SceneSpanCm = FMath::Max3(Span.X, Span.Y, Span.Z);
	const FVector DynamicSpan = DynamicMaximum - DynamicMinimum;
	const float DynamicSpanCm = FMath::Max3(DynamicSpan.X, DynamicSpan.Y, DynamicSpan.Z);
	// The dataset's recommended distance is a photographic full-room value.
	// Start from a short, interior, negative-Y view of the selected group so
	// the bike and both garments occupy the frame together.  The free camera
	// remains available after startup for close inspection.
	float DistanceCm = bDynamicBoundsValid
		? FMath::Clamp(DynamicSpanCm * 1.12f, 220.0f, 360.0f)
		: FMath::Clamp(SceneSpanCm * 0.4f, 450.0f, 700.0f);
	const FVector CameraDirection = FVector(0.25f, -0.95f, 0.08f).GetSafeNormal();
	// The runtime controller continues with RMB/WASD/QE free-camera control.

	if (PresentationBounds.bRoomBoundsValid)
	{
		// Keep the first-person camera inside the ReplicaCAD room shell.  A
		// camera outside the wall sees only the wall's back face and makes the
		// room appear black or occluded.
		constexpr float RoomMarginCm = 100.0f;
		const FVector SafeMin = PresentationBounds.RoomBoundsMinCm + FVector(RoomMarginCm);
		const FVector SafeMax = PresentationBounds.RoomBoundsMaxCm - FVector(RoomMarginCm);
		float MaximumSafeDistanceCm = BIG_NUMBER;
		const auto LimitDistance = [&MaximumSafeDistanceCm, &OutFocus, &CameraDirection](float FocusAxis, float DirectionAxis, float MinAxis, float MaxAxis)
		{
			if (DirectionAxis > KINDA_SMALL_NUMBER)
			{
				MaximumSafeDistanceCm = FMath::Min(MaximumSafeDistanceCm, (MaxAxis - FocusAxis) / DirectionAxis);
			}
			else if (DirectionAxis < -KINDA_SMALL_NUMBER)
			{
				MaximumSafeDistanceCm = FMath::Min(MaximumSafeDistanceCm, (MinAxis - FocusAxis) / DirectionAxis);
			}
		};
		LimitDistance(OutFocus.X, CameraDirection.X, SafeMin.X, SafeMax.X);
		LimitDistance(OutFocus.Y, CameraDirection.Y, SafeMin.Y, SafeMax.Y);
		LimitDistance(OutFocus.Z, CameraDirection.Z, SafeMin.Z, SafeMax.Z);
		DistanceCm = FMath::Min(DistanceCm, FMath::Max(MaximumSafeDistanceCm, 300.0f));
	}
	OutLocation = OutFocus + CameraDirection * DistanceCm;
}

bool ReadMetadataVector(const TSharedPtr<FJsonObject>& Object, const TCHAR* FieldName, FVector& OutVector, float Scale)
{
	const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
	if (!Object.IsValid() || !Object->TryGetArrayField(FieldName, Values) || Values == nullptr || Values->Num() != 3)
	{
		return false;
	}
	OutVector = FVector(
		static_cast<float>((*Values)[0]->AsNumber()) * Scale,
		static_cast<float>((*Values)[1]->AsNumber()) * Scale,
		static_cast<float>((*Values)[2]->AsNumber()) * Scale);
	return true;
}

bool LoadInteractionPresentations(
	TArray<FInteractionBodyPresentation>& OutBodies,
	FReplicaPresentationBounds& OutPresentationBounds)
{
	const FString MetadataPath = FPaths::ConvertRelativePathToFull(
		FPaths::Combine(FPaths::ProjectDir(), TEXT("../outputs/replica_cad/metadata/replica_cad_interaction.json")));
	FString JsonText;
	if (!FFileHelper::LoadFileToString(JsonText, *MetadataPath))
	{
		return false;
	}

	TSharedPtr<FJsonObject> RootObject;
	const TSharedRef<TJsonReader<TCHAR>> Reader = TJsonReaderFactory<TCHAR>::Create(JsonText);
	if (!FJsonSerializer::Deserialize(Reader, RootObject) || !RootObject.IsValid())
	{
		return false;
	}
	const TSharedPtr<FJsonObject>* PresentationObject = nullptr;
	if (RootObject->TryGetObjectField(TEXT("presentation_bounds"), PresentationObject)
		&& PresentationObject != nullptr
		&& PresentationObject->IsValid())
	{
		FVector SceneMinM;
		FVector SceneMaxM;
		FVector FocusM;
		if (ReadMetadataVector(*PresentationObject, TEXT("min_m"), SceneMinM, 100.0f)
			&& ReadMetadataVector(*PresentationObject, TEXT("max_m"), SceneMaxM, 100.0f)
			&& ReadMetadataVector(*PresentationObject, TEXT("focus_m"), FocusM, 100.0f))
		{
			OutPresentationBounds.bValid = true;
			OutPresentationBounds.SceneBoundsMinCm = SceneMinM;
			OutPresentationBounds.SceneBoundsMaxCm = SceneMaxM;
			OutPresentationBounds.FocusCm = FocusM;
			double RecommendedDistanceM = 0.0;
			if ((*PresentationObject)->TryGetNumberField(TEXT("recommended_distance_m"), RecommendedDistanceM))
			{
				OutPresentationBounds.RecommendedDistanceCm = static_cast<float>(RecommendedDistanceM * 100.0);
			}
		}
		FVector RoomMinM;
		FVector RoomMaxM;
		if (ReadMetadataVector(*PresentationObject, TEXT("room_min_m"), RoomMinM, 100.0f)
			&& ReadMetadataVector(*PresentationObject, TEXT("room_max_m"), RoomMaxM, 100.0f))
		{
			OutPresentationBounds.bRoomBoundsValid = true;
			OutPresentationBounds.RoomBoundsMinCm = RoomMinM;
			OutPresentationBounds.RoomBoundsMaxCm = RoomMaxM;
		}
	}
	const TArray<TSharedPtr<FJsonValue>>* BodyValues = nullptr;
	if (!RootObject->TryGetArrayField(TEXT("dynamic_bodies"), BodyValues) || BodyValues == nullptr)
	{
		return false;
	}
	for (const TSharedPtr<FJsonValue>& BodyValue : *BodyValues)
	{
		const TSharedPtr<FJsonObject> BodyObject = BodyValue.IsValid() ? BodyValue->AsObject() : nullptr;
		if (!BodyObject.IsValid())
		{
			continue;
		}
		FInteractionBodyPresentation Presentation;
		if (!BodyObject->TryGetStringField(TEXT("name"), Presentation.ObjectId))
		{
			continue;
		}
		double SourceObjectIdNumber = 0.0;
		if (BodyObject->TryGetNumberField(TEXT("source_object_id"), SourceObjectIdNumber))
		{
			Presentation.SourceObjectId = static_cast<int32>(SourceObjectIdNumber);
		}
		FVector SizeM;
		if (!ReadMetadataVector(BodyObject, TEXT("initial_position_m"), Presentation.InitialLocationCm, 100.0f)
			|| !ReadMetadataVector(BodyObject, TEXT("size_m"), SizeM, 100.0f))
		{
			continue;
		}
		if (BodyObject->HasField(TEXT("visual_mesh_file")))
		{
			BodyObject->TryGetStringField(TEXT("visual_mesh_file"), Presentation.LocalVisualMeshPath);
		}
		if (Presentation.LocalVisualMeshPath.IsEmpty())
		{
			UE_LOG(LogTemp, Warning, TEXT("ReplicaCAD body %s has no visual mesh path; cube fallback will be used"), *Presentation.ObjectId);
		}
		BodyObject->TryGetBoolField(TEXT("deformable"), Presentation.bDeformable);
		if (Presentation.bDeformable)
		{
			const TSharedPtr<FJsonObject>* ClothGridObject = nullptr;
			if (!BodyObject->TryGetObjectField(TEXT("cloth_grid"), ClothGridObject)
				|| ClothGridObject == nullptr
				|| !ClothGridObject->IsValid())
			{
				UE_LOG(LogTemp, Error, TEXT("Deformable ReplicaCAD body %s has no cloth_grid metadata"), *Presentation.ObjectId);
				continue;
			}
			double Cols = 0.0;
			double Rows = 0.0;
			if (!(*ClothGridObject)->TryGetNumberField(TEXT("cols"), Cols)
				|| !(*ClothGridObject)->TryGetNumberField(TEXT("rows"), Rows)
				|| !ReadMetadataVector(*ClothGridObject, TEXT("local_bounds_min_m"), Presentation.ClothLocalBoundsMinCm, 100.0f)
				|| !ReadMetadataVector(*ClothGridObject, TEXT("local_bounds_max_m"), Presentation.ClothLocalBoundsMaxCm, 100.0f))
			{
				UE_LOG(LogTemp, Error, TEXT("Deformable ReplicaCAD body %s has invalid cloth_grid metadata"), *Presentation.ObjectId);
				continue;
			}
			Presentation.ClothGridCols = FMath::Max(2, FMath::RoundToInt(static_cast<float>(Cols)));
			Presentation.ClothGridRows = FMath::Max(2, FMath::RoundToInt(static_cast<float>(Rows)));
		}
		if (Presentation.ObjectId.Contains(TEXT("bike")))
		{
			Presentation.Color = FLinearColor(0.82f, 0.08f, 0.04f, 1.0f);
		}
		else if (Presentation.ObjectId.Contains(TEXT("cloth")))
		{
			Presentation.Color = FLinearColor(0.18f, 0.42f, 0.75f, 1.0f);
		}
		else if (Presentation.ObjectId.Contains(TEXT("box")))
		{
			Presentation.Color = FLinearColor(0.82f, 0.56f, 0.28f, 1.0f);
		}
		else if (Presentation.ObjectId.Contains(TEXT("rack")))
		{
			Presentation.Color = FLinearColor(0.95f, 0.35f, 0.08f, 1.0f);
		}
		else if (Presentation.ObjectId.Contains(TEXT("chair")))
		{
			Presentation.Color = FLinearColor(0.08f, 0.32f, 0.42f, 1.0f);
		}
		else
		{
			Presentation.Color = FLinearColor(0.7f, 0.75f, 0.8f, 1.0f);
		}
		Presentation.FullSizeCm = SizeM;
		OutBodies.Add(MoveTemp(Presentation));
	}
	UE_LOG(LogTemp, Display, TEXT("MuJoCo interaction presentations loaded from %s bodies=%d"), *MetadataPath, OutBodies.Num());
	return OutBodies.Num() > 0;
}

void DrawReplicaCollisionProxyDebug(UWorld* World)
{
	if (World == nullptr)
	{
		return;
	}

	const FString MetadataPath = FPaths::ConvertRelativePathToFull(
		FPaths::Combine(FPaths::ProjectDir(), TEXT("../outputs/metadata/office0_collision_proxy.json")));
	FString JsonText;
	if (!FFileHelper::LoadFileToString(JsonText, *MetadataPath))
	{
		UE_LOG(LogTemp, Warning, TEXT("Replica collision debug metadata was not found: %s"), *MetadataPath);
		return;
	}

	TSharedPtr<FJsonObject> RootObject;
	const TSharedRef<TJsonReader<TCHAR>> Reader = TJsonReaderFactory<TCHAR>::Create(JsonText);
	if (!FJsonSerializer::Deserialize(Reader, RootObject) || !RootObject.IsValid())
	{
		UE_LOG(LogTemp, Warning, TEXT("Replica collision debug metadata is invalid: %s"), *MetadataPath);
		return;
	}

	const TArray<TSharedPtr<FJsonValue>>* ProxyValues = nullptr;
	if (!RootObject->TryGetArrayField(TEXT("proxies"), ProxyValues) || ProxyValues == nullptr)
	{
		UE_LOG(LogTemp, Warning, TEXT("Replica collision debug metadata has no proxies: %s"), *MetadataPath);
		return;
	}

	auto ReadVector3 = [](const TSharedPtr<FJsonObject>& Object, const TCHAR* FieldName, FVector& OutVector) -> bool
	{
		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		if (!Object.IsValid() || !Object->TryGetArrayField(FieldName, Values) || Values == nullptr || Values->Num() != 3)
		{
			return false;
		}
		OutVector = FVector(
			static_cast<float>((*Values)[0]->AsNumber()) * 100.0f,
			static_cast<float>((*Values)[1]->AsNumber()) * 100.0f,
			static_cast<float>((*Values)[2]->AsNumber()) * 100.0f);
		return true;
	};

	for (const TSharedPtr<FJsonValue>& ProxyValue : *ProxyValues)
	{
		const TSharedPtr<FJsonObject> ProxyObject = ProxyValue.IsValid() ? ProxyValue->AsObject() : nullptr;
		FVector Center;
		FVector Extent;
		if (!ProxyObject.IsValid() || !ReadVector3(ProxyObject, TEXT("center_m"), Center) || !ReadVector3(ProxyObject, TEXT("half_size_m"), Extent))
		{
			continue;
		}

		FString Role;
		FString Name;
		FString Confidence;
		ProxyObject->TryGetStringField(TEXT("role"), Role);
		ProxyObject->TryGetStringField(TEXT("name"), Name);
		ProxyObject->TryGetStringField(TEXT("confidence"), Confidence);
		FColor Color = FColor::White;
		if (Role == TEXT("floor"))
		{
			Color = FColor::Green;
		}
		else if (Role == TEXT("wall"))
		{
			Color = FColor::Red;
		}
		else if (Role == TEXT("desk"))
		{
			Color = FColor::Yellow;
		}
		else if (Role == TEXT("bookcase"))
		{
			Color = FColor::Magenta;
		}

		// Use the foreground depth group so opaque visual geometry cannot hide
		// the collision proxy edges. DepthPriority=0 only showed the few edges
		// that happened to be in front of the high-resolution Replica mesh.
		DrawDebugBox(World, Center, Extent, Color, true, -1.0f, 1, 4.0f);
		UE_LOG(
			LogTemp,
			Display,
			TEXT("Collision proxy %s role=%s center_cm=(%.1f,%.1f,%.1f) half_cm=(%.1f,%.1f,%.1f)"),
			*Name,
			*Role,
			Center.X,
			Center.Y,
			Center.Z,
			Extent.X,
			Extent.Y,
			Extent.Z);
		DrawDebugString(
			World,
			Center + FVector(0.0f, 0.0f, Extent.Z + 5.0f),
			FString::Printf(TEXT("collision:%s [%s]"), *Name, *Confidence),
			nullptr,
			Color,
			0.0f,
			true);
	}

	UE_LOG(LogTemp, Display, TEXT("Replica collision debug boxes drawn from %s"), *MetadataPath);
}
}

AMuJoCoBridgeDemoGameMode::AMuJoCoBridgeDemoGameMode()
{
	DefaultPawnClass = nullptr;
	PlayerControllerClass = AMuJoCoBridgeDemoPlayerController::StaticClass();
}

void AMuJoCoBridgeDemoGameMode::BeginPlay()
{
	Super::BeginPlay();

	UWorld* World = GetWorld();
	if (World == nullptr)
	{
		return;
	}

	AReplicaOfficeVisualActor* OfficeVisual = World->SpawnActor<AReplicaOfficeVisualActor>(
		AReplicaOfficeVisualActor::StaticClass(), FVector::ZeroVector, FRotator::ZeroRotator);
	const bool bOfficeVisualLoaded = OfficeVisual != nullptr && OfficeVisual->IsMeshLoaded();

	UStaticMesh* CubeMesh = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
	if (!bOfficeVisualLoaded && CubeMesh != nullptr)
	{
		AStaticMeshActor* Floor = World->SpawnActor<AStaticMeshActor>(AStaticMeshActor::StaticClass(), FVector(0.0f, 0.0f, -5.0f), FRotator::ZeroRotator);
		if (Floor != nullptr)
		{
			UStaticMeshComponent* FloorMesh = Floor->GetStaticMeshComponent();
			FloorMesh->SetStaticMesh(CubeMesh);
			FloorMesh->SetMobility(EComponentMobility::Static);
			FloorMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
			Floor->SetActorScale3D(FVector(5.0f, 5.0f, 0.05f));
		}
	}

	TArray<FInteractionBodyPresentation> InteractionBodies;
	FReplicaPresentationBounds PresentationBounds;
	if (LoadInteractionPresentations(InteractionBodies, PresentationBounds))
	{
	for (int32 BodyIndex = 0; BodyIndex < InteractionBodies.Num(); ++BodyIndex)
		{
			const FInteractionBodyPresentation& Presentation = InteractionBodies[BodyIndex];
			const FTransform BodyTransform(
				FRotator::ZeroRotator,
				Presentation.bDeformable ? FVector::ZeroVector : Presentation.InitialLocationCm);
			if (AMuJoCoBridgeDemoActor* BodyActor = World->SpawnActorDeferred<AMuJoCoBridgeDemoActor>(
				AMuJoCoBridgeDemoActor::StaticClass(), BodyTransform))
			{
				BodyActor->ConfigureForObject(
					Presentation.ObjectId,
					Presentation.FullSizeCm,
					Presentation.Color,
					Presentation.LocalVisualMeshPath,
					BodyIndex == 0,
					Presentation.bDeformable,
					Presentation.ClothGridCols,
					Presentation.ClothGridRows,
					Presentation.ClothLocalBoundsMinCm,
					Presentation.ClothLocalBoundsMaxCm);
				UGameplayStatics::FinishSpawningActor(BodyActor, BodyTransform);
				DrawDebugString(
					World,
					Presentation.InitialLocationCm + FVector(0.0f, 0.0f, Presentation.FullSizeCm.Z * 0.6f),
					FString::Printf(TEXT("MuJoCo %s"), *Presentation.ObjectId),
					nullptr,
					Presentation.Color.ToFColor(true),
					0.0f,
					true);
			}
		}
	}
	else
	{
		World->SpawnActor<AMuJoCoBridgeDemoActor>(AMuJoCoBridgeDemoActor::StaticClass(), FVector(0.0f, 0.0f, 35.0f), FRotator::ZeroRotator);
	}

	// Collision boxes and axis lines are diagnostics, not scene content.  Keep
	// them off in the normal presentation so the semantic visual room is easy
	// to read; the MuJoCo contact names remain visible in the selection overlay.
	constexpr bool bShowCollisionDiagnostics = false;
	if (bShowCollisionDiagnostics)
	{
		DrawDebugLine(World, FVector::ZeroVector, FVector(100.0f, 0.0f, 0.0f), FColor::Red, true, -1.0f, 0, 2.0f);
		DrawDebugLine(World, FVector::ZeroVector, FVector(0.0f, 100.0f, 0.0f), FColor::Green, true, -1.0f, 0, 2.0f);
		DrawDebugLine(World, FVector::ZeroVector, FVector(0.0f, 0.0f, 100.0f), FColor::Blue, true, -1.0f, 0, 2.0f);
		DrawDebugString(World, FVector(110.0f, 0.0f, 0.0f), TEXT("+X"), nullptr, FColor::Red, 0.0f, true);
		DrawDebugString(World, FVector(0.0f, 110.0f, 0.0f), TEXT("+Y"), nullptr, FColor::Green, 0.0f, true);
		DrawDebugString(World, FVector(0.0f, 0.0f, 110.0f), TEXT("+Z"), nullptr, FColor::Blue, 0.0f, true);
		DrawReplicaCollisionProxyDebug(World);
	}

	FVector CameraLocation;
	FVector FocusPoint;
	ComputeReplicaCameraFrame(InteractionBodies, PresentationBounds, CameraLocation, FocusPoint);
	ACameraActor* Camera = World->SpawnActor<ACameraActor>(ACameraActor::StaticClass(), CameraLocation, FRotator::ZeroRotator);
	if (Camera != nullptr)
	{
		Camera->Tags.Add(TEXT("ReplicaRuntimeCamera"));
		Camera->SetActorRotation((FocusPoint - Camera->GetActorLocation()).Rotation());
		UE_LOG(LogTemp, Display, TEXT("Replica camera initialized location=(%.1f,%.1f,%.1f) focus=(%.1f,%.1f,%.1f)"),
			CameraLocation.X,
			CameraLocation.Y,
			CameraLocation.Z,
			FocusPoint.X,
			FocusPoint.Y,
			FocusPoint.Z);
		if (Camera->GetCameraComponent() != nullptr)
		{
			Camera->GetCameraComponent()->SetFieldOfView(72.0f);
		}
		if (APlayerController* PlayerController = UGameplayStatics::GetPlayerController(World, 0))
		{
			PlayerController->SetViewTarget(Camera);
		}
	}

	ADirectionalLight* Light = World->SpawnActor<ADirectionalLight>(ADirectionalLight::StaticClass(), FVector::ZeroVector, FRotator(-45.0f, -35.0f, 0.0f));
	if (Light != nullptr && Light->GetLightComponent() != nullptr)
	{
		// Keep the runtime fill below the editor's existing sun light.  The
		// Replica vertex-color material is already visible without aggressive
		// HDR amplification, which otherwise washes the room to white.
		Light->GetLightComponent()->SetIntensity(0.85f);
		Light->GetLightComponent()->SetLightColor(FLinearColor(1.0f, 0.95f, 0.90f));
	}

	APointLight* InteriorFill = World->SpawnActor<APointLight>(
		APointLight::StaticClass(), FVector(0.0f, -60.0f, 220.0f), FRotator::ZeroRotator);
	if (InteriorFill != nullptr && InteriorFill->PointLightComponent != nullptr)
	{
		UPointLightComponent* FillComponent = InteriorFill->PointLightComponent;
		FillComponent->SetMobility(EComponentMobility::Movable);
		FillComponent->SetIntensity(300.0f);
		FillComponent->SetAttenuationRadius(650.0f);
		FillComponent->SetCastShadows(false);
		FillComponent->SetLightColor(FLinearColor(1.0f, 0.90f, 0.78f));
	}
}
